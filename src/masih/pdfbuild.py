"""
بناء ملف PDF نصّه حروف عربية حقيقية قابلة للنسخ والبحث.

لماذا fpdf2 + uharfbuzz؟ جُرّبت أربعة مسارات على النص نفسه:
    • طباعة المتصفح     → النسخ يخرج مشوّهاً
    • LibreOffice       → رموز (cid:4) بدل الحروف، بأربعة خطوط
    • WeasyPrint        → سليم، لكن تثبيته على ويندوز يحتاج GTK
    • fpdf2 + uharfbuzz → سليم، ويُثبَّت بـ pip وحده بلا مكتبات نظام

════════════════════════════════════════════════════════════════════
لماذا طبقتان: الرسمُ شيءٌ والنسخُ شيء
════════════════════════════════════════════════════════════════════

الخطُّ العربيُّ يُرسم موصولاً، فيحتاج تشكيلاً (shaping) يحوّل الحروفَ
رسوماً متّصلة. و‎fpdf2‎ حين يُشكِّل يكتب الرسومَ في الملفّ بترتيبها
البصريّ — كما تُرى على الورق من اليمين — لا بترتيبها المنطقيّ كما
تُقرأ. فإذا نسخ القارئُ خرج النصُّ مقلوباً:

    المصدر  : الحمدُ لله ربِّ العالمين
    المنسوخ : ينلماعلا  ِّ(cid:8)بر لله ُدملحا

ولا حرفَ ينقص — العدد مطابق — وإنّما انقلب الترتيب. ويزيده سوءاً أنّ
الرباطات (لح، لله) تُخزَّن وحدةً واحدة، فتبقى مستقيمةً حين ينقلب ما
حولها، فيخرج «العاملني» مكان «العالمين»: وهو الذي يُرى انفصالاً في
الألف. وما بقي من رسمٍ لا حرفَ له طبع القارئُ رقمَه ‎(cid:8)‎ فظهرت
الشرطةُ والنجمةُ في وسط الكلام.

والعلاج ألّا نطلب من طبقةٍ واحدة أن تخدم غرضين متضادّين:

    ١) طبقةٌ تُرى ولا تُنسخ: مشكَّلةٌ بـ harfbuzz، بخطٍّ خاصٍّ بالرسم
       تُصرَف خريطةُ نسخه كلُّها إلى ‎U+FEFF‎ (علامةٌ صفريّة العرض)،
       فلا يجد القارئ فيها ما يُخرجه، ولا يطبع ‎(cid:N)‎ لأنّ لكلّ
       رمزٍ سطراً في الخريطة.

    ٢) طبقةٌ تُنسخ ولا تُرى: بلا تشكيل، تُرسم فوق الأولى بنمط العرض
       ‎3 Tr‎ (لا حبرَ ولا قصّ)، بالخطّ الأصل.

فما يقع تحت البصر رسمٌ سليم، وما يقع تحت المؤشّر نصٌّ سليم، ولا
يتزاحمان. وهي الطريقة نفسها التي تسلكها برامج الـ OCR في طبقة النصّ
تحت صورة الصفحة.

────────────────────────────────────────────────────────────────────
وبأيّ ترتيبٍ تُكتب طبقةُ النسخ؟ بالبصريّ، كما يفعل Word
────────────────────────────────────────────────────────────────────

بقي سؤالٌ ثانٍ: أنكتب طبقةَ النسخ بالترتيب المنطقيّ أم البصريّ؟

القارئات تنقسم في العربيّة قسمين لا ثالث لهما:

    • PDFium (محرّك Edge و Chrome) يقلب المقاطعَ العربيّة عند
      الاستخراج — يفترض أنّها مخزَّنةٌ بصريّاً كما تُرسم.
    • pdfminer وأشباهها تأخذ المخزون كما هو بلا قلب.

فأيًّا اخترتَ أرضيتَ واحداً وأغضبتَ الآخر. وقد ظننتُ الأمرَ مستحيلاً
حتى نُبِّهتُ إلى أنّ Word يُصدّر ملفّاتٍ تُنسخ سليمةً في Edge. ففُحص
ملفٌّ من إخراج Word 2010، فإذا أوّلُ مقطعٍ فيه مخزَّنٌ هكذا:

        'يملعلا ثحبلا ةدامع'   ← وهو «عمادة البحث العلمي» مقلوباً

فـ Word يخزّن بالترتيب **البصريّ**، ويقلبه PDFium فيستقيم. وهذا هو
المسلك الذي عليه أكثرُ ما يقرؤه الناس، فسلكناه: ‎visual_order()‎ تعكس
النصّ عكساً يحترم عناقيدَ الحركات ويُبقي الأرقامَ واللاتينيّةَ على
اتّجاهها. فما نكتبه اليوم يُنسخ في Edge كما يُنسخ من Word سواءً بسواء.

والثمن معروفٌ مذكور: أدواتٌ لا تقلب — كـ pdfminer — تقرؤه معكوساً،
وهو ثمنُ ملفّات Word نفسِها منذ عقود.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from html.parser import HTMLParser

from .fonts import find_font, quran_font

try:
    from fpdf import FPDF
except ImportError:  # pragma: no cover - تُفحص عند التشغيل
    FPDF = None

# التشكيل العربي يتم عبر uharfbuzz. بدونه يرسم fpdf2 الحروف منفصلة
# ومن اليسار، فيخرج النص مقلوباً. فلا يُسمح بالمرور صامتاً.
try:
    import uharfbuzz as _hb

    HB_VERSION = getattr(_hb, "__version__", "?")
except ImportError:  # pragma: no cover
    _hb = None
    HB_VERSION = None

PT_TO_MM = 0.3528
HEADING_RATIO = {1: 1.58, 2: 1.30, 3: 1.14, 4: 1.02, 5: 1.02, 6: 1.02}
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
# أزرق بحريّ — لون البرنامج بعد تغيير حلّته إلى الكحلي والعاجي والذهبي.
# ويبقى افتراضياً وحسب: الورقة تحمل لونها في وسمها فيغلب هذا.
DEFAULT_ACCENT = "#2A468B"
INK = (21, 23, 28)


class MissingDependency(RuntimeError):
    """مكتبة لازمة غير مثبَّتة — الرسالة موجَّهة للمستخدم لا للمطوّر."""


# ============================================================ قراءة الورقة
class SheetParser(HTMLParser):
    """يحوّل ورقة المعاينة إلى كتل: عناوين وفقرات وقوائم وجداول."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.style: dict = {}
        self.cur: dict | None = None
        self.runs: list[dict] = []
        self.fmt = {"bold": False, "italic": False, "ayah": False, "code": False}
        self.list_stack: list[dict] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.in_pagemark = False

    def _flush(self) -> None:
        runs = [r for r in self.runs if r["text"].strip()]
        if self.cur and runs:
            self.cur["runs"] = runs
            self.blocks.append(self.cur)
        self.cur, self.runs = None, []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
        cls = a.get("class", "")

        if tag == "meta" and a.get("name") == "masih":
            try:
                self.style = json.loads(a.get("content", "{}"))
            except (ValueError, TypeError):
                pass
            return

        if tag == "table":
            self._flush()
            self.table = []
            return
        if tag == "tr" and self.table is not None:
            self.row = []
            return
        if tag in ("td", "th") and self.row is not None:
            self.cell = []
            return

        if tag in ("b", "strong"):
            self.fmt["bold"] = True
        elif tag in ("i", "em"):
            self.fmt["italic"] = True
        elif tag == "code":
            self.fmt["code"] = True
        elif tag == "span" and "ayah" in cls:
            self.fmt["ayah"] = True
        elif tag == "div" and "page-mark" in cls:
            self._flush()
            self.blocks.append({"type": "pagemark", "num": a.get("data-page", "")})
            self.in_pagemark = True
        elif tag in ("ul", "ol"):
            self.list_stack.append({"ordered": tag == "ol", "i": 0})
        elif tag == "li":
            self._flush()
            lst = self.list_stack[-1] if self.list_stack else {"ordered": False, "i": 0}
            lst["i"] += 1
            self.cur = {"type": "li", "ordered": lst["ordered"], "index": lst["i"]}
        elif tag == "hr":
            self._flush()
            self.blocks.append({"type": "hr"})
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.cur = {"type": "h", "level": int(tag[1])}
        elif tag == "p":
            self._flush()
            self.cur = {"type": "p"}
        elif tag == "pre":
            self._flush()
            self.cur = {"type": "pre"}

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.table is not None:
            if self.table:
                self.blocks.append({"type": "table", "rows": self.table})
            self.table = None
            return
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
            return
        if tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
            return

        if tag in ("b", "strong"):
            self.fmt["bold"] = False
        elif tag in ("i", "em"):
            self.fmt["italic"] = False
        elif tag == "code":
            self.fmt["code"] = False
        elif tag == "span":
            self.fmt["ayah"] = False
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
        elif tag in ("p", "li", "pre", "div") or re.fullmatch(r"h[1-6]", tag):
            if tag == "div":
                self.in_pagemark = False
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)
            return
        if self.in_pagemark:
            return
        if self.cur is not None:
            self.runs.append({"text": data, **self.fmt})


def parse_sheet(html: str) -> SheetParser:
    """يُفكّك ورقة HTML إلى كتل قابلة للرسم. مفصولة لتسهيل الاختبار."""
    parser = SheetParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser


# ============================================================ الرسم
def _hex_to_rgb(value: str, default: str = DEFAULT_ACCENT) -> tuple[int, int, int]:
    raw = (value or default).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raw = default.lstrip("#")
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _arabic_number(n: int | str) -> str:
    return "".join(ARABIC_DIGITS[int(d)] if d.isdigit() else d for d in str(n))


def require_dependencies() -> None:
    """يتحقق من المكتبات قبل أي عمل، برسالة يفهمها المستخدم."""
    if FPDF is None:
        raise MissingDependency(
            "مكتبة fpdf2 غير مثبَّتة.\nثبّتها بـ:  pip install fpdf2 uharfbuzz")
    if _hb is None:
        raise MissingDependency(
            "مكتبة uharfbuzz غير مثبَّتة، وبدونها يخرج النص العربي مقلوباً.\n"
            "ثبّتها بـ:  pip install uharfbuzz")


# ================================================ الطبقتان: رسمٌ ونسخ
"""
كلُّ خطٍّ يُضاف مرّتين تحت اسمين: اسمٌ للرسم واسمٌ للنسخ. والملفّ على
القرص واحد، لكنّ ‎fpdf2‎ يُنشئ لكلّ اسمٍ مورداً مستقلّاً في الـ PDF —
وهذا هو المقصود: مورد الرسم تُعمى خريطتُه، ومورد النسخ تبقى سليمة.

ولا يُنسخ ملفّ الخطّ إلى القرص: الاسم وحده يكفي ‎fpdf2‎ ليفصل المَورِدين.
"""
_DRAW_SUFFIX = "@d"

# مقطعٌ يُكتب من اليسار فلا تُعكس حروفُه: أرقامٌ ولاتينيّةٌ وما يلتصق بها.
_LTR_RUN = re.compile(r"[0-9A-Za-z٠-٩]"
                      r"[0-9A-Za-z٠-٩.,:/\-]*")


def visual_order(text: str) -> str:
    """
    يقلب النصَّ إلى ترتيبه البصريّ، كما يخزّنه Word في ملفّاته.

    ثلاث قواعد يقوم عليها القلب:
      • الحركةُ تتبع حرفها فتُضمّ إليه عنقوداً واحداً.
      • الأرقامُ والحروفُ اللاتينيّة تُنقل مواضعُها ولا تُقلب حروفُها،
        فـ «255» تبقى «255» ولا تصير «552».
      • كلُّ عنقودٍ يُقلب داخليّاً، لأن PDFium يقلب حرفاً حرفاً عند
        الاستخراج، فيعود العنقودُ إلى صورته الأولى.

    ‎visual_order(visual_order(s))‎ تعيد ‎s‎ نفسها فيما عدا ترتيبَ
    الحركات داخل العنقود، وهو ما لا يُغيّر النصَّ بعد التوحيد (NFC).
    """
    units: list[str] = []
    index = 0
    for match in _LTR_RUN.finditer(text):
        units.extend(text[index:match.start()])
        units.append(match.group())
        index = match.end()
    units.extend(text[index:])

    merged: list[str] = []
    for unit in units:
        if len(unit) == 1 and unicodedata.combining(unit) and merged:
            merged[-1] += unit
        else:
            merged.append(unit)

    out: list[str] = []
    for unit in reversed(merged):
        out.append(unit[::-1] if len(unit) > 1 and not _LTR_RUN.fullmatch(unit)
                   else unit)
    return "".join(out)


def _wrap_lines(pdf: "FPDF", text: str, width: float) -> list[str]:
    """
    يكسر النصَّ أسطراً بعرضٍ معلوم، بالخطّ والحجم القائمين الآن.

    ولا نعتمد على كسر ‎multi_cell‎ لأنّا نحتاج السطورَ نصّاً لنقلب كلَّ
    سطرٍ على حدة. والقياسُ بالخطّ نفسه والعرض نفسه، فالكسرُ واحد.
    """
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        row = ""
        for word in words:
            probe = word if not row else row + " " + word
            if row and pdf.get_string_width(probe) > width:
                lines.append(row)
                row = word
            else:
                row = probe
        lines.append(row)
    return lines


class _Layers:
    """يرسم النصّ مرّتين: مشكَّلاً يُرى، ومنطقيّاً يُنسخ ولا يُرى."""

    def __init__(self, pdf: "FPDF") -> None:
        self.pdf = pdf

    def _draw_name(self, font: str) -> str:
        return font + _DRAW_SUFFIX

    def multi_cell(self, w, h, text, *, font, style, size, align,
                   indent=0.0) -> None:
        """
        يكتب فقرةً بالطبقتين، ويترك المؤشّر حيث تركته الطبقةُ المرئيّة.

        الطبقةُ المرئيّة هي وحدها التي تقود التصفّح: هي التي تكسر
        الصفحةَ إذا امتلأت. ثمّ تُعاد الطبقةُ الخفيّة إلى أوّل الفقرة
        وتُرسم على الصفحات نفسها بلا كسرٍ تلقائيّ — إذ لو كُسرت لها
        صفحةٌ ثانية أضافت للملفّ ورقةً بيضاء لا سبب لها.

        وما دام النصُّ واحداً والخطُّ واحداً والعرضُ واحداً، فكسرُ
        الأسطر واحدٌ في الطبقتين، فتقع كلُّ فقرةٍ فوق أختها.
        """
        pdf = self.pdf
        left = pdf.l_margin + indent
        y0, page0 = pdf.get_y(), pdf.page

        # ١) المرئيّة — مشكَّلة، وهي التي تكسر الصفحات
        pdf.set_font(self._draw_name(font), style, size)
        pdf.set_text_shaping(True, direction="rtl")
        pdf.set_x(left)
        pdf.multi_cell(w, h, text, align=align, new_x="LMARGIN", new_y="NEXT")
        end_y, end_page = pdf.get_y(), pdf.page

        # ٢) المنسوخة — بلا تشكيل، غير مرئيّة، فوق الأولى
        pdf.page = page0
        auto, margin = pdf.auto_page_break, pdf.b_margin
        pdf.set_auto_page_break(False)
        pdf.set_font(font, style, size)
        pdf.set_text_shaping(False)
        pdf.set_xy(left, y0)
        pdf._out("BT 3 Tr ET")
        try:
            # سطراً سطراً، وكلُّ سطرٍ مقلوبٌ بصريّاً على حدة: القلبُ على
            # الفقرة كلِّها يقلب ترتيبَ سطورها فيختلط أوّلُها بآخرها.
            for row in _wrap_lines(pdf, text, w):
                pdf.set_x(left)
                pdf.cell(w, h, visual_order(row), align=align,
                         new_x="LMARGIN", new_y="NEXT")
        finally:
            pdf._out("BT 0 Tr ET")
            pdf.set_text_shaping(True, direction="rtl")
            pdf.set_auto_page_break(auto, margin)

        pdf.page = end_page
        pdf.set_y(end_y)

    def cell(self, w, h, text, *, font, style, size, align, x, y) -> None:
        """خليّةٌ بسطرٍ واحد — للعلامات وأرقام الصفحات."""
        pdf = self.pdf
        pdf.set_font(self._draw_name(font), style, size)
        pdf.set_text_shaping(True, direction="rtl")
        pdf.set_xy(x, y)
        pdf.cell(w, h, text, align=align, new_x="LEFT", new_y="TOP")

        pdf.set_font(font, style, size)
        pdf.set_text_shaping(False)
        pdf.set_xy(x, y)
        pdf._out("BT 3 Tr ET")
        try:
            pdf.cell(w, h, visual_order(text), align=align,
                     new_x="LEFT", new_y="TOP")
        finally:
            pdf._out("BT 0 Tr ET")
            pdf.set_text_shaping(True, direction="rtl")


def _blind_draw_fonts(data: bytes, pdf: "FPDF") -> bytes:
    """
    يصرف خريطةَ نسخ خطوط الرسم كلَّها إلى علامةٍ صفريّة العرض.

    لا تُحذف الخريطة: القارئ إذا لم يجد للرمز سطراً طبع رقمَه ‎(cid:N)‎.
    بل يُكتب لكلّ رمزٍ في الخطّ سطرٌ يصرفه إلى ‎U+FEFF‎ — حرفٌ قياسيّ
    صفريُّ العرض تبتلعه القارئات صامتةً. فتبقى الطبقةُ المرئيّة بلا
    نصٍّ يُنسَخ، ويأتي النصُّ كلُّه من الطبقة المنطقيّة تحتها.

    وإن تعذّر شيء رُدَّ الملفُّ كما هو: ملفٌّ نسخُه مزدوج خيرٌ من لا ملف.
    """
    draw: dict[int, set[int]] = {}
    for key, font in pdf.fonts.items():
        # مفتاح fpdf2 هو الاسم ملحوقاً بالنمط: ‎"body@d"‎ و‎"body@dB"‎.
        # فالعلامة تقع في وسط المفتاح لا في آخره.
        if _DRAW_SUFFIX not in str(key):
            continue
        idx = getattr(font, "i", None)
        subset = getattr(font, "subset", None)
        if idx is None or subset is None:
            continue
        codes = {int(c) for g, c in subset.items() if g is not None}
        if codes:
            draw[int(idx)] = codes
    if not draw:
        return data

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:  # pragma: no cover - pypdf مضمَّنة في التنفيذيّ
        return data
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
        seen: set[int] = set()
        for page in writer.pages:
            resources = page.get("/Resources")
            fonts_res = resources.get_object().get("/Font") if resources else None
            if not fonts_res:
                continue
            for name, ref in fonts_res.get_object().items():
                key = str(name).lstrip("/")
                if not key.startswith("F") or not key[1:].isdigit():
                    continue
                codes = draw.get(int(key[1:]))
                if not codes:
                    continue
                tu = ref.get_object().get("/ToUnicode")
                if tu is None:
                    continue
                stream = tu.get_object()
                if id(stream) in seen:
                    continue
                seen.add(id(stream))
                stream.set_data(_blank_cmap(stream.get_data(), codes))
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - لا يجوز أن يُسقط الإعماءُ البناءَ
        return data


def _blank_cmap(data: bytes, codes: set[int]) -> bytes:
    """يستبدل بجداول الخريطة جدولاً يصرف كلّ رمزٍ إلى ‎U+FEFF‎."""
    data = re.sub(rb"\d+\s+beginbfchar.*?endbfchar\s*", b"", data, flags=re.S)
    data = re.sub(rb"\d+\s+beginbfrange.*?endbfrange\s*", b"", data, flags=re.S)
    blocks: list[bytes] = []
    ordered = sorted(codes)
    for start in range(0, len(ordered), _BFCHAR_PER_BLOCK):
        chunk = ordered[start:start + _BFCHAR_PER_BLOCK]
        body = b"".join(b"<%04X> <%04X>\n" % (c, _INVISIBLE) for c in chunk)
        blocks.append(b"%d beginbfchar\n" % len(chunk) + body + b"endbfchar\n")
    return data.replace(b"endcmap", b"".join(blocks) + b"endcmap", 1)


def build_pdf(html: str) -> bytes:
    """يبني ملف PDF من ورقة المعاينة ويُرجع محتواه بايتاتٍ."""
    require_dependencies()

    parser = parse_sheet(html)
    st = parser.style
    family = st.get("font", "Traditional Arabic")
    size = float(st.get("size", 13) or 13)
    line = float(st.get("line", 1.95) or 1.95)
    accent = _hex_to_rgb(st.get("accent", DEFAULT_ACCENT))

    regular = find_font(family) or find_font("amiri")
    if not regular:
        raise MissingDependency("لم يُعثر على أي خط عربي على هذا الجهاز.")
    bold = find_font(family, bold=True) or regular
    quran = quran_font() or regular

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(18, 20, 18)
    pdf.set_auto_page_break(True, margin=20)
    # كلُّ خطٍّ مرّتين: اسمٌ للنسخ واسمٌ للرسم. انظر شرح الطبقتين أعلى الملفّ.
    for name, path, style_ in (("body", regular, ""), ("body", bold, "B"),
                               ("quran", quran, "")):
        pdf.add_font(name, style_, str(path))
        pdf.add_font(name + _DRAW_SUFFIX, style_, str(path))
    pdf.set_text_shaping(True, direction="rtl")
    pdf.set_lang("ar")
    pdf.add_page()

    layers = _Layers(pdf)
    line_mm = size * line * PT_TO_MM
    content_w = pdf.w - pdf.l_margin - pdf.r_margin

    def text_of(runs) -> str:
        return "".join(r["text"] for r in runs)

    def para(runs, fsize, colour=INK, style="", align="R",
             font="body", before=0.0, after=3.0, indent=0.0) -> None:
        if before:
            pdf.ln(before)
        pdf.set_text_color(*colour)
        # المحاذاة يميناً لا الضبط من الطرفين: fpdf2 يترك السطر الأخير
        # في الفقرة العربية منزاحاً إلى اليسار عند الضبط.
        layers.multi_cell(content_w - indent, fsize * line * PT_TO_MM,
                          text_of(runs), font=font, style=style, size=fsize,
                          align=align, indent=indent)
        if after:
            pdf.ln(after * 0.35)

    for block in parser.blocks:
        kind = block["type"]

        if kind == "h":
            para(block["runs"], size * HEADING_RATIO.get(block["level"], 1.0),
                 accent, "B", align="R", before=3.5, after=1.5)

        elif kind == "p":
            has_ayah = any(r.get("ayah") for r in block["runs"])
            para(block["runs"], size,
                 font="quran" if has_ayah else "body", align="R")

        elif kind == "li":
            marker = (_arabic_number(block["index"]) + "."
                      if block.get("ordered") else "•")
            indent = 8.0
            # لو لم يبقَ في الصفحة ما يسع سطراً، انتقل قبل رسم العلامة
            # حتى لا تنفصل العلامة عن نصّها بين صفحتين.
            if pdf.get_y() + line_mm > pdf.h - pdf.b_margin:
                pdf.add_page()
            y = pdf.get_y()
            pdf.set_text_color(*accent)
            layers.cell(indent, line_mm, marker, font="body", style="",
                        size=size, align="R",
                        x=pdf.w - pdf.r_margin - indent, y=y)
            pdf.set_text_color(*INK)
            pdf.set_xy(pdf.l_margin, y)
            layers.multi_cell(content_w - indent, line_mm,
                              text_of(block["runs"]), font="body", style="",
                              size=size, align="R")
            pdf.ln(0.26 * size * PT_TO_MM)

        elif kind == "pre":
            para(block["runs"], size * 0.88, align="L", after=0.9)

        elif kind == "hr":
            pdf.set_draw_color(200, 205, 212)
            y = pdf.get_y() + 2
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(5)

        elif kind == "pagemark":
            pdf.ln(3)
            pdf.set_text_color(*accent)
            layers.multi_cell(content_w, line_mm * 0.7,
                              f"— {block.get('num', '')} —", font="body",
                              style="", size=size * 0.72, align="C")
            pdf.ln(2)

        elif kind == "table":
            # الجدول يرسمه fpdf2 بنفسه خليّةً خليّة، فلا سبيل إلى دسّ
            # طبقةٍ خفيّةٍ تحت كلّ خليّة. فيُرسم بخطّ النسخ وحده: خريطتُه
            # سليمة فالنسخ منه صحيح، وهو المطلوب — والفرق في الوصل
            # لا يكاد يُرى في خلايا الجدول القصيرة.
            pdf.set_font("body", "", size * 0.92)
            pdf.set_text_color(*INK)
            pdf.set_draw_color(204, 209, 217)
            with pdf.table(text_align="RIGHT", line_height=line_mm * 0.9,
                           borders_layout="ALL") as table:
                for cells in block["rows"]:
                    row = table.row()
                    for cell in cells:
                        row.cell(cell)
            pdf.ln(2)

    # أوّلاً تُرمَّم خرائط خطوط النسخ، ثم تُعمى خرائط خطوط الرسم.
    # والترتيب مقصود: الترميم يمرّ على الخطوط كلّها، فلو أُخّر لأعاد
    # إلى خطّ الرسم حروفَه التي أُعميت.
    data = repair_tounicode(bytes(pdf.output()), pdf.fonts.values())
    return _blind_draw_fonts(data, pdf)


# ================================================ إصلاح خريطة النسخ
"""
لماذا يخرج النسخ من الملف مليئاً بحروف إنجليزية وأرقام.

الحرف العربي المشكَّل يصير عند التشكيل أكثرَ من رسم: رسمٌ للحرف
ورسمٌ للحركة، وقد يجمع الخطُّ الشدّةَ والحركةَ في رسم واحد ويُبقي
معهما رسماً ثالثاً. وخريطة النسخ (ToUnicode) تُبنى في fpdf2 على أن
أوّل رسم في العنقود يأخذ حروفه كلَّها، فيبقى ما بعده بلا حرف، فلا
يُكتب له في الخريطة سطر أصلاً.

والقارئ إذا لم يجد للرمز سطراً في الخريطة لم يمتنع، بل عرضه بقيمته
العددية حرفاً لاتينياً: فالرمز ٩ جدولةٌ، و٤٢ نجمة، و٦١ يساوي، و٢٥٦
حرف Ā. ومن هنا جاء «ا67 َأْلعْظَمِي» و«H 67» و«Ā¢» في النصّ المنسوخ.

والعلاج الأمثل ليس ترقيعَ ما نقص من خريطة fpdf2، بل بناءَ الخريطة
كلِّها من جديد من مصدرٍ واحدٍ حاسمٍ لا يكذب: جدولُ الرموز في الخطّ
نفسه. لكل خطٍّ رموزُه، ولكل رمزٍ حروفُه إن كانت له حروف. فيُقرأ
جدول fpdf2 كاملاً، ويُكتب في الخريطة سطرٌ لكل رمز، وسطرٌ فارغ
لكلّ رمزٍ لا حرف له.

وبهذا لا تعتمد سلامةُ النسخ على أن يحسن fpdf2 توزيعَ الحروف على
الرسوم — يكفي أن يعرف رسومه.
"""
_CODE_IN_MAP = re.compile(rb"<([0-9A-Fa-f]{4})>\s*<")
_BFCHAR_PER_BLOCK = 100          # سقف الكتلة الواحدة في معيار PDF


"""رمز ‹علامة ترتيب البايت› U+FEFF بديلاً عن السطر الفارغ ‎<>‎.

بعضُ قارئات الـ PDF لا تفهم السطرَ الفارغ في خريطة النسخ، فتُرجع بدل
عدم الإخراج قيمةَ الرمز بيتاً لاتينياً — ومن هنا جاء «Ā¢®» في النسخ.
والحلّ أن نُعطي القارئ حرفاً حقيقيّاً عديمَ الشكل والتباعد يستهلكه
ويسكت: علامةُ ترتيب البايت U+FEFF قياسيّةٌ في اليونيكود صفريّةُ العرض،
تقبلها كل قارئة وتظهر مطويّةً في النصّ المنسوخ.

ولا نستدلّ باسم الرسم على الحرف: أسماء الرسوم في الخطوط العربية أحياناً
أسماء صلاتٍ ورباطات (ligatures) لا حروف مفردة، فيؤدّي استخراج الحرف
من الاسم إلى تكرار حرفٍ ورد مرّةً في عنقود الرسم الأوّل. فأسلم أن نُعطي
كلّ رمزٍ ضاع حرفُه علامةً صامتة، فلا يفقد شيءٌ ولا يتكرّر شيء.
"""
_INVISIBLE = 0xFEFF


def _font_entries(font) -> dict[int, tuple[int, ...]]:
    """يبني {رمز → حروفه} من فهرس خطّ fpdf2 واحد."""
    out: dict[int, tuple[int, ...]] = {}
    subset = getattr(font, "subset", None)
    if subset is None:
        return out
    for glyph, code in subset.items():
        if glyph is None:
            continue
        chars = getattr(glyph, "unicode", None)
        if isinstance(chars, tuple) and chars:
            out[int(code)] = tuple(chars)
        else:
            out[int(code)] = (_INVISIBLE,)
    return out


def _splice_missing(stream, entries: dict[int, tuple[int, ...]]) -> bool:
    """يُضيف للخريطة سطراً لكلّ رمزٍ لا سطر له فيها، ويترك القائم كما هو."""
    data = stream.get_data()
    if b"beginbfchar" not in data:
        return False
    present = {int(m.group(1), 16) for m in _CODE_IN_MAP.finditer(data)}
    missing = sorted(k for k in entries if k not in present)
    if not missing:
        return False
    blocks: list[str] = []
    for start in range(0, len(missing), _BFCHAR_PER_BLOCK):
        chunk = missing[start:start + _BFCHAR_PER_BLOCK]
        body = []
        for code in chunk:
            chars = entries[code]
            body.append(f'<{code:04X}> <{"".join(f"{c:04X}" for c in chars)}>\n')
        blocks.append(f"{len(chunk)} beginbfchar\n{''.join(body)}endbfchar\n")
    stream.set_data(data.replace(b"endcmap",
                                 "".join(blocks).encode("latin-1") + b"endcmap",
                                 1))
    return True


def repair_tounicode(data: bytes, fonts) -> bytes:
    """
    يُعيد الملف نفسه بعد ضمّ الرموز الناقصة إلى خريطة النسخ لكل خطّ.

    كلّ خطٍّ في fpdf2 يحمل رقماً ‎`i`‎ يظهر في مورد الـ PDF باسم ‎/Fi‎.
    فنُطابق كلّ خطّ بمورده بالرقم — لا بالاسم — فلا نضمّ رموز خطٍّ إلى
    مورد خطٍّ آخر. ثم نضيف لكل مورد ما ينقصه من رموز خطّه: كلّ رمزٍ
    غير مذكورٍ في خريطته يُضاف بحروفه إن ثبتت، أو بسطرٍ فارغ إن لم
    تثبت. ولا نمسّ سطراً قائماً — فما بناه fpdf2 صحيحاً يبقى.

    وإن تعذّر شيء — لغياب pypdf أو لتغيّر بنية fpdf2 — رُدَّ الملف كما هو:
    ملفٌ نسخُه ناقص خيرٌ من لا ملف. واختبارٌ يحرس هذا الطريق إن انكسر.
    """
    per_index: dict[int, dict[int, tuple[int, ...]]] = {}
    for font in fonts:
        idx = getattr(font, "i", None)
        if idx is None:
            continue
        entries = _font_entries(font)
        if entries:
            per_index[int(idx)] = entries
    if not per_index:
        return data
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:  # pragma: no cover - pypdf مضمَّنة في الملف التنفيذي
        return data
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
        seen: set[int] = set()
        changed = False
        for page in writer.pages:
            resources = page.get("/Resources")
            fonts_res = resources.get_object().get("/Font") if resources else None
            if not fonts_res:
                continue
            for name, ref in fonts_res.get_object().items():
                # اسم المورد ‎"/Fi"‎ رقمُه هو رقمُ خطّ fpdf2 نفسه.
                key = str(name).lstrip("/")
                if not key.startswith("F") or not key[1:].isdigit():
                    continue
                entries = per_index.get(int(key[1:]))
                if not entries:
                    continue
                tu_ref = ref.get_object().get("/ToUnicode")
                if tu_ref is None:
                    continue
                stream = tu_ref.get_object()
                if id(stream) in seen:
                    continue
                seen.add(id(stream))
                changed |= _splice_missing(stream, entries)
        if not changed:
            return data
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - لا يجوز أن يُسقط الإصلاحُ البناءَ
        return data


# ============================================================ فحص النتيجة
def extracted_text(data: bytes) -> str:
    """يستخرج نصّ الصفحة الأولى — يُستعمل للفحص الذاتي والاختبارات."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        return PdfReader(io.BytesIO(data)).pages[0].extract_text() or ""
    except Exception:  # noqa: BLE001 - الفحص لا يجوز أن يُسقط البناء
        return ""


def selectable_report(data: bytes) -> str:
    """وصف قصير لحالة النص داخل الملف، يُكتب في السجل."""
    text = extracted_text(data)
    if not text:
        return ""
    if "(cid:" in text:
        return "النص غير قابل للنسخ"
    arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
    return f"قابل للنسخ ({arabic} حرفاً عربياً)" if arabic else ""


def self_test() -> str:
    """
    يبني صفحة صغيرة ويتأكد أن كل سطر التصق بحافة اليمين.

    هذا هو الفحص الذي يكشف غياب التشكيل: بدون uharfbuzz ينزاح النص
    إلى اليسار وتظهر الحروف منفصلة.
    """
    if FPDF is None or _hb is None:
        return "معطَّل — مكتبة ناقصة"
    font = find_font("Traditional Arabic")
    if not font:
        return "لا يوجد خط عربي"
    try:
        pdf = FPDF(format="A4", unit="mm")
        pdf.set_margins(18, 20, 18)
        pdf.add_font("t", "", str(font))
        pdf.set_font("t", size=14)
        pdf.set_text_shaping(True, direction="rtl")
        pdf.add_page()
        pdf.multi_cell(0, 10,
                       "هذا نص عربي طويل نسبيا يمتد على اكثر من سطر واحد "
                       "لكي نقيس محاذاة كل سطر على حدة ونتاكد من سلامتها",
                       align="R", new_x="LMARGIN", new_y="NEXT")
        data = bytes(pdf.output())
    except Exception as exc:  # noqa: BLE001
        return f"فشل: {exc}"

    try:
        import pdfplumber
    except ImportError:
        return "سليم (بلا فحص بصري)"
    try:
        with pdfplumber.open(io.BytesIO(data)) as doc:
            page = doc.pages[0]
            words = page.extract_words()
            if not words:
                return "لم يُرسم أي نص"
            edge = page.width - 18 * 2.8346  # حافة اليمين بالنقاط
            lines: dict[int, list] = {}
            for w in words:
                lines.setdefault(round(w["top"]), []).append(w)
            gaps = [edge - max(w["x1"] for w in ln) for ln in lines.values()]
            if max(gaps) > 8:
                return f"منزاح ({max(gaps):.0f} نقطة)"
            return "سليم"
    except Exception as exc:  # noqa: BLE001
        return f"فشل الفحص البصري: {exc}"
