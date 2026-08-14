"""
اختبارات الجزء البايثوني: بناء الـ PDF، والخادم، وسلامة الموارد.

تشغيل:  python -m unittest discover -s tests -v
تستعمل unittest المدمجة عمداً، فلا تحتاج تثبيت أي حزمة اختبار.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from masih import asset                                        # noqa: E402
from masih import fonts, pdfbuild, server, window              # noqa: E402

ARABIC = "بسم الله الرحمن الرحيم والحمد لله رب العالمين"

# نصّ مشكَّل كامل التشكيل — وهو موضع العطب: الحركة والشدّة تُخرجان
# من الخطّ رسوماً زائدة لا حرف لها، فتخرج في النسخ حروفاً لاتينية.
VOCALISED = (
    "الصَّحَابِيُّ الْجَلِيلُ أَبُو هُرَيْرَةَ رَضِيَ اللَّهُ عَنْهُ",
    "تَأْلِيفُ الدُّكْتُورِ مُحَمَّدٍ ضِيَاءُ الرَّحْمَنِ الْأَعْظَمِي",
    "الْأُسْتَاذُ بِالْجَامِعَةِ الْإِسْلَامِيَّةِ بِالْمَدِينَةِ النَّبَوِيَّةِ",
)
VOCALISED_SHEET = "".join(f"<p>{line}</p>" for line in VOCALISED)

SHEET = """<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="masih" content='{"font":"Amiri","size":13,"line":1.9,"accent":"#123a6b"}'>
</head><body>
<h1>عنوان الوثيقة</h1>
<p>فقرة فيها <strong>نص عريض</strong> وكلام عادي.</p>
<p><span class="ayah">﴿الحمد لله رب العالمين﴾</span></p>
<ul><li>بند أول</li><li>بند ثانٍ</li></ul>
<div class="page-mark" data-page="7"><span>٧</span></div>
<table><tr><th>العمود</th><th>الثاني</th></tr><tr><td>قيمة</td><td>أخرى</td></tr></table>
<hr>
</body></html>"""


# ===================================================== تحليل الورقة
class ParseSheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parsed = pdfbuild.parse_sheet(SHEET)

    def test_reads_style_meta(self) -> None:
        """إعدادات المعاينة تُنقل إلى الـ PDF، فلا يختلف الملف عمّا يُرى."""
        self.assertEqual(self.parsed.style["font"], "Amiri")
        self.assertEqual(self.parsed.style["size"], 13)
        self.assertEqual(self.parsed.style["accent"], "#123a6b")

    def test_finds_every_block_kind(self) -> None:
        kinds = [b["type"] for b in self.parsed.blocks]
        for expected in ("h", "p", "li", "pagemark", "table", "hr"):
            self.assertIn(expected, kinds, f"لم يُرصد نوع الكتلة {expected}")

    def test_heading_level_and_text(self) -> None:
        head = next(b for b in self.parsed.blocks if b["type"] == "h")
        self.assertEqual(head["level"], 1)
        self.assertIn("عنوان", "".join(r["text"] for r in head["runs"]))

    def test_marks_ayah_runs(self) -> None:
        """الآية تُرسم بخط المصحف، فلا بدّ من تمييز مقاطعها."""
        ayah_runs = [r for b in self.parsed.blocks if b["type"] == "p"
                     for r in b.get("runs", []) if r.get("ayah")]
        self.assertTrue(ayah_runs, "لم يُميَّز أي مقطع كآية")

    def test_page_mark_number_not_leaked_into_text(self) -> None:
        """رقم الصفحة يُرسم وحده؛ تسرّبه إلى الفقرة يُفسد النص."""
        mark = next(b for b in self.parsed.blocks if b["type"] == "pagemark")
        self.assertEqual(mark["num"], "7")

    def test_table_rows_and_cells(self) -> None:
        table = next(b for b in self.parsed.blocks if b["type"] == "table")
        self.assertEqual(len(table["rows"]), 2)
        self.assertEqual(table["rows"][0], ["العمود", "الثاني"])

    def test_ordered_list_numbering(self) -> None:
        parsed = pdfbuild.parse_sheet("<ol><li>واحد</li><li>اثنان</li></ol>")
        items = [b for b in parsed.blocks if b["type"] == "li"]
        self.assertEqual([i["index"] for i in items], [1, 2])
        self.assertTrue(all(i["ordered"] for i in items))

    def test_empty_sheet_is_not_an_error(self) -> None:
        self.assertEqual(pdfbuild.parse_sheet("").blocks, [])

    def test_default_accent_is_the_navy_of_the_new_skin(self) -> None:
        """حلّة البرنامج صارت كحلياً وعاجياً وذهبياً، فليتبعها الـ PDF."""
        self.assertEqual(pdfbuild.DEFAULT_ACCENT.lower(), "#2a468b")
        self.assertEqual(pdfbuild._hex_to_rgb(""), (0x2A, 0x46, 0x8B))


# ===================================================== الخطوط
class FontTests(unittest.TestCase):
    def test_quran_font_is_bundled(self) -> None:
        """خط المصحف مرفق، فلا يعتمد الإخراج على ما هو مثبَّت."""
        path = fonts.quran_font()
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())

    def test_unknown_family_falls_back(self) -> None:
        """عائلة غير موجودة لا تُسقط البناء، بل تعود إلى بديل مرفق."""
        self.assertIsNotNone(fonts.find_font("خط لا وجود له إطلاقاً"))

    def test_bold_never_returns_none_when_regular_exists(self) -> None:
        self.assertIsNotNone(fonts.find_font("Amiri", bold=True))


# ===================================================== بناء الـ PDF
@unittest.skipIf(pdfbuild.FPDF is None or pdfbuild._hb is None,
                 "fpdf2 أو uharfbuzz غير مثبَّت")
class BuildPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf = pdfbuild.build_pdf(SHEET)

    def test_produces_a_pdf(self) -> None:
        self.assertTrue(self.pdf.startswith(b"%PDF-"))
        self.assertGreater(len(self.pdf), 1000)

    def test_text_is_selectable_not_glyph_ids(self) -> None:
        """
        جوهر البرنامج كلّه.

        الطرق الأخرى تُخرج ملفاً يبدو سليماً، لكن نسخ نصّه يُعطي
        (cid:4) أو حروفاً مبعثرة. هذا الاختبار يمنع ذلك من العودة.
        """
        text = pdfbuild.extracted_text(self.pdf)
        self.assertNotIn("(cid:", text, "النص خرج رموزاً لا حروفاً")
        arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
        self.assertGreater(arabic, 20, f"لم يُستخرج نص عربي كافٍ: {text[:120]!r}")

    def test_selftest_passes(self) -> None:
        """الفحص الذاتي يكشف غياب التشكيل — يجب أن يبقى سليماً."""
        self.assertTrue(pdfbuild.self_test().startswith("سليم"),
                        pdfbuild.self_test())

    def test_plain_arabic_round_trips(self) -> None:
        pdf = pdfbuild.build_pdf(f"<p>{ARABIC}</p>")
        text = pdfbuild.extracted_text(pdf)
        self.assertIn("الله", text.replace("\n", " "))

    def test_vocalised_arabic_round_trips_exactly(self) -> None:
        """
        النصّ المشكَّل يخرج من الملف كما دخل، حرفاً بحرف.

        كان يخرج ممزَّقاً: «الص  َّحَابِي  ُّ» بفواصل، وفيه حروف لاتينية
        وأرقام دخيلة — لأن رسوم الحركات لم يكن لها سطر في خريطة النسخ،
        فيعرضها القارئ بقيمتها العددية حرفاً لاتينياً.

        وتُستثنى علاماتُ ترتيب البايت U+FEFF من المقارنة: نستعملها بديلاً
        عن السطر الفارغ في خريطة النسخ، وهي صفريّة العرض والتباعد وتذهب
        تلقائياً في أغلب برامج التحرير عند اللصق. المُهمّ ألّا يخرج
        بديلها حرفاً لاتينياً مرئياً — وذلك ما يمسكه اختبار الدخلاء.
        """
        text = pdfbuild.extracted_text(pdfbuild.build_pdf(VOCALISED_SHEET))
        clean = text.replace("﻿", "")
        for line in VOCALISED:
            self.assertIn(line, clean, f"لم يخرج كما دخل: {line}")

    def test_copied_text_has_no_latin_intruders(self) -> None:
        """لا حرف لاتيني ولا رقم في نسخِ صفحةٍ كلُّها عربية."""
        text = pdfbuild.extracted_text(pdfbuild.build_pdf(VOCALISED_SHEET))
        source = {c for c in re.sub(r"<[^>]*>", " ", VOCALISED_SHEET)
                  if c.isascii() and not c.isspace()}
        intruders = sorted({c for c in text
                            if c.isascii() and not c.isspace()} - source)
        self.assertEqual(intruders, [], f"دخلت رموز أجنبية: {intruders}")

    def test_blinding_the_draw_font_is_load_bearing(self) -> None:
        """
        يُثبت أن إعماء خطّ الرسم هو ما يمنع ازدواج النصّ المنسوخ.

        الطبقة المرئيّة مشكَّلةٌ مخزَّنةٌ بترتيبٍ بصريّ، والخفيّة هي
        طبقةُ النسخ. فلو بقيت خريطةُ نسخ خطّ الرسم سليمةً لخرج النصّ
        مرّتين: مرّةً من هذه ومرّةً من تلك. فإن سقط هذا الاختبار يوماً
        فقد تغيّر شيءٌ في بنية الطبقتين — لا يجوز حذف الإعماء قبل فهمه.
        """
        with mock.patch.object(pdfbuild, "_blind_draw_fonts",
                               lambda data, pdf: data):
            raw = pdfbuild.extracted_text(pdfbuild.build_pdf(VOCALISED_SHEET))
        # بلا إعماء يخرج السطر مرّتين: من طبقة الرسم ومن طبقة النسخ.
        self.assertGreater(
            raw.replace("﻿", "").count(VOCALISED[0]), 1,
            "لم يتضاعف النصّ بلا إعماء — راجع بنية الطبقتين")

    def test_visual_order_round_trips(self) -> None:
        """القلبُ البصريُّ مرّتين يعيد النصَّ كما كان."""
        for line in list(VOCALISED) + [ARABIC,
                                       "الآيةُ رقم 255 من سورةِ البقرةِ"]:
            self.assertEqual(
                pdfbuild.visual_order(pdfbuild.visual_order(line)), line,
                f"لم يعُد كما كان: {line}")

    def test_visual_order_keeps_digits_forward(self) -> None:
        """الأرقامُ لا تُقلب: «255» تبقى «255»."""
        self.assertIn("255", pdfbuild.visual_order("الآيةُ رقم 255 من سورة"))
        self.assertIn("1445", pdfbuild.visual_order("سنة 1445 هـ"))

    def test_bad_accent_colour_does_not_crash(self) -> None:
        """قيمة لون تالفة تعود إلى الافتراضي بدل إسقاط البناء."""
        sheet = ('<meta name="masih" content=\'{"accent":"ليس لوناً"}\'>'
                 "<p>نص</p>")
        self.assertTrue(pdfbuild.build_pdf(sheet).startswith(b"%PDF-"))

    def test_long_list_spans_pages(self) -> None:
        """القوائم الطويلة تنتقل بين الصفحات بلا انفصال العلامة عن نصّها."""
        items = "".join(f"<li>بند رقم {i} من قائمة طويلة</li>" for i in range(90))
        pdf = pdfbuild.build_pdf(f"<ul>{items}</ul>")
        self.assertTrue(pdf.startswith(b"%PDF-"))


# ===================================================== الموارد
class AssetTests(unittest.TestCase):
    def test_all_assets_present(self) -> None:
        for rel in [("index.html",), ("quran.json",), ("quran-engine.js",),
                    ("favicon.svg",), ("fonts", "AmiriQuran.ttf"),
                    ("fonts", "Amiri-Regular.ttf"), ("fonts", "Amiri-Bold.ttf"),
                    ("fonts", "AmiriQuran-Regular.woff2")]:
            self.assertTrue(asset(*rel).is_file(), f"المورد ناقص: {'/'.join(rel)}")

    def test_quran_data_is_complete(self) -> None:
        data = json.loads(asset("quran.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data), 114)
        self.assertEqual(sum(len(s["verses"]) for s in data), 6236)

    def test_page_loads_nothing_from_the_internet(self) -> None:
        """
        البرنامج يعمل بلا اتصال. أي رابط خارجي في الصفحة يكسر ذلك
        بصمت: تظهر الخطوط بديلة ويتعطّل التدقيق دون رسالة واضحة.
        """
        page = asset("index.html").read_text(encoding="utf-8")
        for needle in ("https://cdn.", "http://cdn.", "jsdelivr", "fonts.googleapis"):
            self.assertNotIn(needle, page,
                             f"الصفحة ما زالت تُحمّل «{needle}» من الإنترنت")

    def test_page_references_the_engine(self) -> None:
        page = asset("index.html").read_text(encoding="utf-8")
        self.assertIn('src="/quran-engine.js', page)

    def test_engine_exposes_what_the_page_calls(self) -> None:
        """
        الصفحة تنادي المحرّك بأسماء؛ فقدان أحدها يكسر التدقيق كلّه
        دون أن يظهر خطأ إلا وقت الاستعمال.
        """
        engine = asset("quran-engine.js").read_text(encoding="utf-8")
        page = asset("index.html").read_text(encoding="utf-8")
        for name in re.findall(r"\bQE\.(\w+)", page):
            self.assertRegex(engine, rf"\b{name}\s*:",
                             f"الصفحة تنادي QE.{name} وهو غير مُصدَّر")


# ===================================================== الخادم
class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = server.create(0)          # منفذ يختاره النظام
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path: str):
        return urllib.request.urlopen(self.base + path, timeout=5)

    def test_health_identifies_the_app(self) -> None:
        """يميّز نسخة ماسح عن أي برنامج آخر يحتلّ المنفذ نفسه."""
        payload = json.loads(self.get("/health").read())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["app"], "masih")

    def test_serves_the_page(self) -> None:
        body = self.get("/").read().decode("utf-8")
        self.assertIn("<title>ماسح</title>", body)

    def test_serves_quran_and_engine_and_icon(self) -> None:
        self.assertEqual(len(json.loads(self.get("/quran.json").read())), 114)
        self.assertIn(b"QuranEngine", self.get("/quran-engine.js").read())
        self.assertIn(b"<svg", self.get("/favicon.svg").read())

    def test_serves_bundled_font(self) -> None:
        reply = self.get("/fonts/AmiriQuran.ttf")
        self.assertEqual(reply.status, 200)
        self.assertGreater(len(reply.read()), 10000)

    def test_font_route_cannot_escape_its_folder(self) -> None:
        """اسم الملف يُقشَّر من أي مسار، فلا يُقرأ ما خارج مجلد الخطوط."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/fonts/../../../../Windows/win.ini")
        self.assertEqual(caught.exception.code, 404)

    def test_unknown_route_is_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/no-such-route")
        self.assertEqual(caught.exception.code, 404)

    def test_rejects_post_from_another_origin(self) -> None:
        """
        الخادم يستمع على الجهاز نفسه، فأي موقع يزوره المستخدم يستطيع
        مخاطبته. فحص الأصل يمنع استعماله من صفحة أجنبية.
        """
        request = urllib.request.Request(
            self.base + "/pdf", data=b"<p>x</p>", method="POST",
            headers={"Origin": "https://example.com"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_ocr_without_key_is_rejected(self) -> None:
        request = urllib.request.Request(
            self.base + "/ocr", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 401)

    @unittest.skipIf(pdfbuild.FPDF is None or pdfbuild._hb is None,
                     "fpdf2 أو uharfbuzz غير مثبَّت")
    def test_builds_pdf_over_http(self) -> None:
        request = urllib.request.Request(
            self.base + "/pdf", data=SHEET.encode("utf-8"), method="POST",
            headers={"Content-Type": "text/html; charset=utf-8",
                     "Origin": self.base})
        body = urllib.request.urlopen(request, timeout=60).read()
        self.assertTrue(body.startswith(b"%PDF-"))

    def test_heartbeat_keeps_the_program_alive(self) -> None:
        life = server.Lifecycle()
        life.touch()
        self.assertFalse(life.expired())

    def test_farewell_shortens_the_deadline_without_killing_instantly(self) -> None:
        """
        الوداع لا يُنهي البرنامج فوراً.

        قد يفتح المستخدم نافذتين على الوثيقة نفسها؛ فإغلاق إحداهما
        لا يجوز أن يقطع الأخرى وهو يعمل عليها.
        """
        life = server.Lifecycle()
        life.farewell()
        self.assertFalse(life.expired(), "أُنهي البرنامج فور إغلاق نافذة واحدة")
        self.assertEqual(life._deadline, server.Lifecycle.FAREWELL_GRACE)

    def test_a_live_window_cancels_a_farewell(self) -> None:
        """نبضة من نافذة باقية تُلغي الإنهاء وتُعيد المهلة الكاملة."""
        life = server.Lifecycle()
        life.farewell()
        life.touch()
        self.assertEqual(life._deadline, server.Lifecycle.TIMEOUT)
        self.assertFalse(life.expired())

    def test_silence_past_the_deadline_expires(self) -> None:
        life = server.Lifecycle()
        life.touch()
        life._last -= server.Lifecycle.TIMEOUT + 1
        self.assertTrue(life.expired(), "لم ينتهِ رغم انقطاع النبض")


# ===================================================== مسار الحفظ والسجل
class SaveDirTests(unittest.TestCase):
    """مجلد الحفظ: افتراضُه، وفحصُ ما يختاره المستخدم."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="masih-t-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_default_is_the_downloads_folder(self) -> None:
        folder = server.default_save_dir()
        self.assertEqual(folder.name, "Downloads")
        self.assertTrue(folder.is_absolute())
        self.assertTrue(folder.is_dir(), "مجلد التنزيلات لم يُنشأ")

    @unittest.skipUnless(sys.platform == "win32", "سؤال الصدَفة خاصّ بويندوز")
    def test_downloads_is_asked_of_the_shell_not_guessed(self) -> None:
        """
        المستخدم قد ينقل مجلد التنزيلات إلى قرص آخر، فالتخمين
        %USERPROFILE%\\Downloads يعطيه مجلداً فارغاً لا يفتحه أحد.
        """
        folder = server._shell_downloads()
        self.assertIsNotNone(folder, "لم تُسأل الصدَفة عن مجلد التنزيلات")
        self.assertTrue(folder.is_absolute())

    def test_relative_path_is_refused_with_an_arabic_reason(self) -> None:
        path, why = server.check_dir("كتبي/هنا")
        self.assertIsNone(path)
        self.assertTrue(any("\u0600" <= c <= "\u06ff" for c in why),
                        f"سبب الرفض ليس عربياً: {why}")

    def test_empty_path_is_refused(self) -> None:
        self.assertIsNone(server.check_dir("   ")[0])

    def test_a_missing_folder_is_created(self) -> None:
        target = self.tmp / "جديد" / "أعمق"
        path, why = server.check_dir(str(target))
        self.assertIsNotNone(path, why)
        self.assertTrue(target.is_dir())

    def test_a_file_is_not_a_folder(self) -> None:
        """مسارٌ يشير إلى ملف قائم لا يُقبل مجلداً للحفظ."""
        blocked = self.tmp / "ملف.txt"
        blocked.write_text("x", encoding="utf-8")
        path, why = server.check_dir(str(blocked))
        self.assertIsNone(path, "قُبل ملفٌ مجلداً للحفظ")
        self.assertTrue(why)

    def test_the_probe_file_is_not_left_behind(self) -> None:
        """الفحص يكتب ملفاً ليتأكّد؛ نسيانُه يترك قمامة في مجلد المستخدم."""
        server.check_dir(str(self.tmp))
        self.assertEqual(list(self.tmp.iterdir()), [])


class FileNameTests(unittest.TestCase):
    """اشتقاق اسم الملف من عنوان الكتاب — وهو مدخل غير موثوق."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="masih-n-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_separators_and_dot_dot_are_stripped(self) -> None:
        stem = server.safe_stem(r"..\..\..\Windows\System32\evil")
        self.assertNotIn("\\", stem)
        self.assertNotIn("/", stem)
        self.assertNotIn("..", stem)

    def test_reserved_device_names_are_escaped(self) -> None:
        """CON.md يفشل إنشاؤه على ويندوز مهما كان امتداده."""
        for name in ("CON", "prn", "COM1", "LPT9", "nul"):
            self.assertNotIn(server.safe_stem(name).upper(), server._RESERVED,
                             f"الاسم المحجوز مرّ كما هو: {name}")

    def test_trailing_dots_and_spaces_go(self) -> None:
        self.assertEqual(server.safe_stem("كتاب . . "), "كتاب")

    def test_empty_title_still_gets_a_name(self) -> None:
        self.assertTrue(server.safe_stem("   "))

    def test_length_is_capped(self) -> None:
        self.assertLessEqual(len(server.safe_stem("ب" * 500)), server.MAX_STEM)

    def test_hostile_title_cannot_escape_the_folder(self) -> None:
        """
        الحاجز الأخير: المسار بعد الحلّ يجب أن يبقى ابن مجلد الحفظ.

        عنوان الكتاب قد يأتي من نصّ ممسوح لا من يد المستخدم، فلا يُؤمَن.
        """
        for hostile in (r"..\..\..\Windows\System32\hack", "../../etc/passwd",
                        r"C:\Windows\System32\drivers\etc\hosts", "..", "....",
                        "\\\\خادم\\مشاركة\\كتاب"):
            target = server.unique_md_path(self.tmp, hostile, set())
            self.assertEqual(target.parent, self.tmp.resolve(),
                             f"خرج الملف من مجلد الحفظ: {hostile} → {target}")
            self.assertEqual(target.suffix, ".md")

    def test_same_title_does_not_overwrite(self) -> None:
        first = server.unique_md_path(self.tmp, "كتاب الطهارة", set())
        first.write_text("أول", encoding="utf-8")
        second = server.unique_md_path(self.tmp, "كتاب الطهارة",
                                       {first.name.lower()})
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(encoding="utf-8"), "أول")


class AtomicWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="masih-a-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_failed_write_leaves_the_old_book_whole(self) -> None:
        """
        جوهر الكتابة الذرّية: انقطاعٌ في المنتصف لا يجوز أن يترك كتاب
        المستخدم مبتوراً. الكتابة المباشرة تقصّ الملف قبل أن تملأه.
        """
        target = self.tmp / "كتاب.md"
        server.atomic_write(target, "النصّ الأصلي كاملاً")
        with mock.patch.object(server.os, "fsync",
                               side_effect=OSError("قُطع القرص")):
            with self.assertRaises(OSError):
                server.atomic_write(target, "نصّ جديد")
        self.assertEqual(target.read_text(encoding="utf-8"), "النصّ الأصلي كاملاً")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["كتاب.md"],
                         "بقي ملف مؤقت في مجلد المستخدم")


class SessionsOverHttpTests(unittest.TestCase):
    """
    الإعدادات والجلسات عبر HTTP حقيقي، على منفذ يختاره النظام.

    المنفذ 7860 لا يُلمس: نسخة المستخدم تعمل عليه بوثائقه.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = Path(tempfile.mkdtemp(prefix="masih-data-"))
        cls.save = Path(tempfile.mkdtemp(prefix="masih-save-"))
        # مجلد البيانات يُقرأ من البيئة في كل نداء، فتحويله يكفي لعزل
        # الاختبار عن %LOCALAPPDATA%\Masih الحقيقي.
        cls._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(cls.data)})
        cls._env.start()
        # وحتى قبل ضبط الإعدادات لا يُكتب شيء في مجلد تنزيلات المستخدم
        cls._downloads = mock.patch.object(server, "default_save_dir",
                                           lambda: cls.save)
        cls._downloads.start()

        cls.server = server.create(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls._downloads.stop()
        cls._env.stop()
        shutil.rmtree(cls.data, ignore_errors=True)
        shutil.rmtree(cls.save, ignore_errors=True)

    def setUp(self) -> None:
        self.call("POST", "/settings", {"saveDir": str(self.save)})

    def call(self, method: str, path: str, body=None, origin: str | None = None):
        """يُرجع (الرمز، الحمولة) ولا يرمي عند رمز خطأ."""
        data = (json.dumps(body, ensure_ascii=False).encode("utf-8")
                if body is not None else None)
        headers = {"Origin": self.base if origin is None else origin}
        if data is not None:
            headers["Content-Type"] = "application/json"
        # سطر الطلب لا يحمل إلا ASCII، فالمعرّف العربي يُرمَّز — والخادم
        # يفكّ الترميز عنده، وهذا ما يُختبَر ضمناً هنا.
        request = urllib.request.Request(self.base + quote(path, safe="/?=&"),
                                         data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as reply:
                return reply.status, json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def make(self, title: str, markdown: str = "# باب", pages: int = 1):
        code, payload = self.call("POST", "/sessions",
                                  {"title": title, "markdown": markdown,
                                   "pages": pages})
        self.assertEqual(code, 200, payload)
        return payload

    # ------------------------------------------------------------ الإعدادات
    def test_settings_report_the_chosen_and_the_default(self) -> None:
        code, payload = self.call("GET", "/settings")
        self.assertEqual(code, 200)
        self.assertEqual(Path(payload["saveDir"]), self.save.resolve())
        self.assertEqual(payload["defaultDir"], str(self.save))

    def test_a_chosen_path_survives_a_restart(self) -> None:
        """الإعداد يُكتب في ملف، فلا يضيع بإغلاق البرنامج."""
        target = self.save / "مجلدي"
        code, payload = self.call("POST", "/settings", {"saveDir": str(target)})
        self.assertEqual(code, 200, payload)
        stored = json.loads((self.data / "Masih" / "settings.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(Path(stored["saveDir"]), target.resolve())
        self.assertEqual(Path(self.call("GET", "/settings")[1]["saveDir"]),
                         target.resolve())

    def test_an_unusable_path_is_refused_with_400(self) -> None:
        blocked = self.save / "ملف-لا-مجلد.txt"
        blocked.write_text("x", encoding="utf-8")
        for bad in ("كتبي", "", str(blocked)):
            code, payload = self.call("POST", "/settings", {"saveDir": bad})
            self.assertEqual(code, 400, f"قُبل مسار غير صالح: {bad!r}")
            self.assertTrue(payload.get("error"))

    def test_a_refused_path_does_not_replace_the_good_one(self) -> None:
        self.call("POST", "/settings", {"saveDir": "نسبي"})
        self.assertEqual(Path(self.call("GET", "/settings")[1]["saveDir"]),
                         self.save.resolve())

    # ------------------------------------------------------------- الجلسات
    def test_a_book_round_trips(self) -> None:
        made = self.make("كتاب الطهارة", "# باب الوضوء\n\nنصّ الكتاب", 12)
        self.assertEqual(made["pages"], 12)
        self.assertEqual(made["chars"], len("# باب الوضوء\n\nنصّ الكتاب"))
        self.assertTrue(Path(made["file"]).is_file())
        self.assertEqual(Path(made["file"]).suffix, ".md")
        code, one = self.call("GET", f"/sessions/{made['id']}")
        self.assertEqual(code, 200)
        self.assertEqual(one["markdown"], "# باب الوضوء\n\nنصّ الكتاب")
        self.assertEqual(one["created"], made["created"])

    def test_the_md_file_is_real_and_readable_from_disk(self) -> None:
        """المطلوب ملف md حقيقي في مجلد المستخدم، لا نصّاً في قاعدة."""
        made = self.make("كتاب المياه", "# المياه")
        self.assertEqual(Path(made["file"]).read_text(encoding="utf-8"), "# المياه")
        self.assertEqual(Path(made["file"]).parent, self.save.resolve())

    def test_updating_keeps_the_same_file(self) -> None:
        made = self.make("كتاب الصلاة", "أول")
        code, again = self.call("POST", "/sessions",
                                {"id": made["id"], "title": "كتاب الصلاة",
                                 "markdown": "أول وثانٍ", "pages": 4})
        self.assertEqual(code, 200, again)
        self.assertEqual(again["id"], made["id"])
        self.assertEqual(again["file"], made["file"])
        self.assertEqual(again["created"], made["created"])
        self.assertEqual(Path(made["file"]).read_text(encoding="utf-8"), "أول وثانٍ")

    def test_updating_an_unknown_id_is_404(self) -> None:
        code, _ = self.call("POST", "/sessions",
                            {"id": "لا-وجود", "title": "x", "markdown": "y"})
        self.assertEqual(code, 404)

    def test_two_books_with_the_same_title_do_not_overwrite(self) -> None:
        first = self.make("مجموع الفتاوى", "الأول")
        second = self.make("مجموع الفتاوى", "الثاني")
        self.assertNotEqual(first["file"], second["file"])
        self.assertEqual(Path(first["file"]).read_text(encoding="utf-8"), "الأول")
        self.assertEqual(Path(second["file"]).read_text(encoding="utf-8"), "الثاني")

    def test_a_hostile_title_writes_inside_the_save_folder(self) -> None:
        """عنوان معادٍ لا يكتب خارج مجلد الحفظ ولا يدوس ملفات النظام."""
        made = self.make(r"..\..\..\Windows\System32\drivers\etc\hosts", "ضار")
        written = Path(made["file"]).resolve()
        self.assertEqual(written.parent, self.save.resolve(), written)
        self.assertTrue(written.is_relative_to(self.save.resolve()))

    def test_a_reserved_name_still_produces_a_file(self) -> None:
        made = self.make("CON", "نصّ")
        self.assertTrue(Path(made["file"]).is_file())
        self.assertNotEqual(Path(made["file"]).stem.upper(), "CON")

    def test_the_list_is_newest_first(self) -> None:
        titles = ["كتاب أ", "كتاب ب", "كتاب ج"]
        made = [self.make(t) for t in titles]
        # التحديث يقدّم الأقدم إلى الصدارة
        self.call("POST", "/sessions", {"id": made[0]["id"], "title": titles[0],
                                        "markdown": "جديد", "pages": 1})
        code, payload = self.call("GET", "/sessions")
        self.assertEqual(code, 200)
        stamps = [item["updated"] for item in payload["sessions"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        ids = [item["id"] for item in payload["sessions"]]
        for item in made:
            self.assertIn(item["id"], ids)
        for key in ("id", "title", "file", "pages", "chars", "created", "updated"):
            self.assertIn(key, payload["sessions"][0])

    def test_a_file_deleted_outside_the_app_is_reported_not_crashed(self) -> None:
        """المستخدم قد ينقل كتابه أو يحذفه؛ فلا يسقط البرنامج ولا يصمت."""
        made = self.make("كتاب ضائع", "نصّ")
        Path(made["file"]).unlink()
        code, one = self.call("GET", f"/sessions/{made['id']}")
        self.assertEqual(code, 200)
        self.assertTrue(one.get("missing"))
        self.assertTrue(one.get("error"))
        self.assertEqual(one["markdown"], "")
        listed = self.call("GET", "/sessions")[1]["sessions"]
        entry = next(i for i in listed if i["id"] == made["id"])
        self.assertTrue(entry.get("missing"))

    def test_unknown_session_is_404(self) -> None:
        self.assertEqual(self.call("GET", "/sessions/لا-وجود-له")[0], 404)

    def test_delete_forgets_the_entry_but_keeps_the_book(self) -> None:
        """
        ملف الـ md وثيقة المستخدم لا ملفٌّ من ملفاتنا.

        حذفه من زرٍّ في قائمة عملٌ لا يُتراجَع عنه، وقد يكون الكتاب
        ثمرة مئة صفحة ممسوحة.
        """
        made = self.make("كتاب يُنسى", "نصّ باقٍ")
        code, payload = self.call("DELETE", f"/sessions/{made['id']}")
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["file"], made["file"])
        self.assertTrue(Path(made["file"]).is_file(), "حُذف ملف المستخدم!")
        self.assertEqual(self.call("GET", f"/sessions/{made['id']}")[0], 404)

    def test_deleting_twice_is_404(self) -> None:
        made = self.make("كتاب مكرّر الحذف")
        self.call("DELETE", f"/sessions/{made['id']}")
        self.assertEqual(self.call("DELETE", f"/sessions/{made['id']}")[0], 404)

    def test_a_torn_index_does_not_lose_the_program(self) -> None:
        """فهرس تالف يُعامَل معاملة الفارغ بدل أن يمنع فتح البرنامج."""
        index = self.data / "Masih" / "sessions.json"
        index.write_text("{ليس", encoding="utf-8")
        self.assertEqual(self.call("GET", "/sessions"), (200, {"sessions": []}))
        self.assertEqual(self.make("كتاب بعد العطب")["title"], "كتاب بعد العطب")

    def test_a_body_that_is_not_json_is_400(self) -> None:
        request = urllib.request.Request(
            self.base + "/sessions", data="ليس json".encode("utf-8"), method="POST",
            headers={"Origin": self.base, "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_a_session_without_markdown_is_refused(self) -> None:
        self.assertEqual(self.call("POST", "/sessions", {"title": "بلا نصّ"})[0], 400)

    # -------------------------------------------------------- المجلد الأصيل
    def test_pick_folder_says_501_when_there_is_no_native_window(self) -> None:
        """
        في ‎--no-window وفي صدَفة المتصفّح لا حوار أصيل، فتُخبَر الواجهة
        لترتدّ إلى حقل النصّ بدل أن تنتظر نافذةً لن تُفتح.
        """
        code, payload = self.call("POST", "/pick-folder")
        self.assertEqual(code, 501)
        self.assertTrue(payload["error"])

    def test_pick_folder_returns_the_chosen_path(self) -> None:
        with mock.patch.object(window, "_active", object()), \
             mock.patch.object(window, "pick_folder", lambda start="": str(self.save)):
            code, payload = self.call("POST", "/pick-folder")
        self.assertEqual(code, 200, payload)
        self.assertEqual(payload["path"], str(self.save))

    def test_cancelling_the_picker_is_not_an_error(self) -> None:
        with mock.patch.object(window, "_active", object()), \
             mock.patch.object(window, "pick_folder", lambda start="": None):
            code, payload = self.call("POST", "/pick-folder")
        self.assertEqual(code, 200, payload)
        self.assertTrue(payload["cancelled"])

    def test_reveal_opens_the_containing_folder(self) -> None:
        made = self.make("كتاب يُكشف")
        opened: list[str] = []
        with mock.patch.object(server.subprocess, "Popen",
                               lambda cmd, **kw: opened.append(cmd)), \
             mock.patch.object(server.os, "startfile",
                               lambda p: opened.append(p), create=True):
            code, payload = self.call("POST", "/reveal", {"path": made["file"]})
        self.assertEqual(code, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(opened, "لم يُنادَ المستكشف")
        self.assertIn(Path(made["file"]).name, str(opened[0]))

    def test_reveal_of_a_vanished_path_is_404(self) -> None:
        code, _ = self.call("POST", "/reveal",
                            {"path": str(self.save / "لا-وجود.md")})
        self.assertEqual(code, 404)

    # ------------------------------------------------------------- الأصل
    def test_a_foreign_page_cannot_read_the_books(self) -> None:
        """
        الخادم يستمع على الجهاز نفسه، فأي موقع يزوره المستخدم يخاطبه.
        وكتبه ومساراته ليست معروضة لمن هبّ ودبّ.
        """
        evil = "https://example.com"
        for method, path in (("GET", "/sessions"), ("GET", "/settings"),
                             ("GET", "/sessions/أيّ")):
            code, _ = self.call(method, path, origin=evil)
            self.assertEqual(code, 403, f"{method} {path} مرّ من أصل أجنبي")

    def test_a_foreign_page_cannot_write_or_delete(self) -> None:
        evil = "https://example.com"
        made = self.make("كتاب محميّ")
        cases = [("POST", "/sessions", {"title": "دخيل", "markdown": "x"}),
                 ("POST", "/settings", {"saveDir": "C:\\"}),
                 ("POST", "/pick-folder", None),
                 ("POST", "/reveal", {"path": made["file"]}),
                 ("DELETE", f"/sessions/{made['id']}", None)]
        for method, path, body in cases:
            code, _ = self.call(method, path, body, origin=evil)
            self.assertEqual(code, 403, f"{method} {path} مرّ من أصل أجنبي")
        self.assertEqual(self.call("GET", f"/sessions/{made['id']}")[0], 200)

    def test_the_heartbeat_still_works_beside_the_new_routes(self) -> None:
        """لا يجوز أن تكسر الإضافات دورة حياة البرنامج."""
        self.assertEqual(self.call("POST", "/alive")[0], 200)
        self.assertEqual(self.call("POST", "/bye")[0], 200)


# ===================================================== صدَفة النافذة
class WindowShellTests(unittest.TestCase):
    """
    النافذة الأصيلة لا تُفتح في الاختبار — تحتاج شاشة وحلقة رسائل.

    فيُختبر ما يُختبر بلا شاشة: أن ما يُطفئ المتصفّح مذكور فعلاً، وأن
    الحَرَس لا يخنق مفاتيح البرنامج، وأن الطريق الاحتياطي سالك.
    """

    def test_mutes_the_two_settings_that_matter(self) -> None:
        """قائمة النقر الأيمن ومفاتيح المتصفّح هما شكوى المستخدم نفسها."""
        self.assertIn("AreDefaultContextMenusEnabled", window._MUTED)
        self.assertIn("AreBrowserAcceleratorKeysEnabled", window._MUTED)

    def test_guard_lets_the_key_through_to_the_page(self) -> None:
        """
        الحَرَس يمنع تصرّف المتصفّح لا وصول المفتاح.

        الواجهة تربط Ctrl+F ببحثها الداخلي؛ فلو أوقف الحَرَس انتشار
        الحدث لقتل بحث البرنامج وهو يظنّ نفسه يقتل بحث المتصفّح.
        """
        self.assertNotIn("stopPropagation()", window._GUARD_JS)
        self.assertNotIn("stopImmediatePropagation()", window._GUARD_JS)
        self.assertIn("preventDefault()", window._GUARD_JS)

    def test_guard_reads_the_physical_key_not_the_letter(self) -> None:
        """لوحة المفاتيح عربية غالباً، فحرف مفتاح F يصل «ب» لا «f»."""
        self.assertIn("e.code", window._GUARD_JS)
        self.assertIn("KeyF", window._GUARD_JS)

    def test_guard_covers_the_context_menu(self) -> None:
        self.assertIn("contextmenu", window._GUARD_JS)

    def test_icon_path_is_short_enough_for_windows(self) -> None:
        """
        تحميل أيقونة من مسار طويل يقتل خيط النافذة بلا رسالة.

        المستودع قد يجلس في مسار عميق، فلا يكفي أن الأيقونة موجودة.
        """
        path = window._icon_path()
        if path is not None:
            self.assertLess(len(path), 260, "مسار الأيقونة أطول ممّا يحتمل ويندوز")
            self.assertTrue(Path(path).is_file())

    def test_falls_back_to_a_browser_without_webview2(self) -> None:
        """جهاز بلا WebView2 يجب أن يفتح البرنامج لا أن يعجز عنه."""
        opened: list[str] = []
        original = (window.webview2_installed, window._open_external)
        window.webview2_installed = lambda: False
        window._open_external = lambda url: opened.append(url) or True
        try:
            native = window.open_window("http://127.0.0.1:7860/")
        finally:
            window.webview2_installed, window._open_external = original
        self.assertFalse(native, "ادّعى نافذة أصيلة بلا WebView2")
        self.assertEqual(opened, ["http://127.0.0.1:7860/"])

    def test_does_not_touch_pywebview_without_webview2(self) -> None:
        """
        استيراد pywebview بلا WebView2 يُرجعه إلى محرّك إنترنت إكسبلورر
        ويكتب مفاتيح في سجلّ ويندوز ليُفعّله — أثرٌ في جهاز المستخدم لا
        مبرّر له، ومحرّكٌ لا يفهم الواجهة.
        """
        original = (window.webview2_installed, window._open_external)
        window.webview2_installed = lambda: False
        window._open_external = lambda url: True
        loaded_before = "webview.platforms.winforms" in sys.modules
        try:
            window.open_window("http://127.0.0.1:7860/")
        finally:
            window.webview2_installed, window._open_external = original
        self.assertEqual("webview.platforms.winforms" in sys.modules,
                         loaded_before, "استُوردت صدَفة pywebview بلا داعٍ")

    def test_folder_picker_refuses_loudly_without_a_window(self) -> None:
        """
        الخادم يسأل النافذة عن حوار المجلدات؛ فإن لم تكن هناك نافذة
        وجب أن يُقال ذلك صراحة لا أن يُرجَع مسارٌ مخترَع تكتب فيه كتب
        المستخدم.
        """
        self.assertIsNone(window._active)
        with self.assertRaises(RuntimeError):
            window.pick_folder()

    def test_pywebview_still_offers_what_the_picker_needs(self) -> None:
        """
        اختيار المجلد يُنادى في نافذة حيّة لا في الاختبار، فلا يكشف
        الاختبارُ تغيّرَ واجهة pywebview إلا هنا: يُتحقَّق من وجود ثابت
        حوار المجلدات وأن create_file_dialog ما زالت تقبل directory.

        ولا يُستورد pywebview إلا مع WebView2: استيراده بدونه يكتب في
        سجلّ ويندوز كما في test_does_not_touch_pywebview_without_webview2.
        """
        if not window.webview2_installed():
            self.skipTest("WebView2 غير مثبَّت")
        try:
            import inspect

            import webview
        except ImportError:
            self.skipTest("pywebview غير مثبَّت")
        dialogs = getattr(webview, "FileDialog", None)
        self.assertTrue(getattr(dialogs, "FOLDER", None) is not None
                        or hasattr(webview, "FOLDER_DIALOG"),
                        "لم يعد في pywebview ثابتٌ لحوار المجلدات")
        params = inspect.signature(webview.Window.create_file_dialog).parameters
        self.assertIn("directory", params)

    def test_closing_nothing_is_harmless(self) -> None:
        """الخادم ينادي close_window عند كل إنهاء، ولو لم تكن هناك نافذة."""
        window.close_window()

    def test_no_native_window_is_reported_when_none_is_open(self) -> None:
        """
        عليها يتوقّف تجاهل انقطاع النبض.

        لو كذبت وقالت «مفتوحة» بلا نافذة، لبقي خادم بلا واجهة يعمل أبداً.
        """
        self.assertFalse(window.native_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
