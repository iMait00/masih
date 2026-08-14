"""
فحص قبول للملف التنفيذي المبنيّ — يُشغّله فعلاً ويخاطبه عبر الشبكة.

اختبارات الوحدة تفحص الشيفرة، وهذا يفحص الحزمة: هل وصلت الموارد
داخل الـ exe؟ هل يقلع بلا نافذة أوامر؟ هل ينتهي حين تُغلق النافذة؟

    python tools/smoke_exe.py _dist/masih.exe
"""

from __future__ import annotations

import json
import subprocess
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SHEET = """<meta charset="utf-8">
<meta name="masih" content='{"font":"Amiri","size":13,"line":1.9,"accent":"#8f1d13"}'>
<h1>وثيقة تجربة</h1>
<p>بسم الله الرحمن الرحيم، والحمد لله رب العالمين.</p>
<p><span class="ayah">﴿الحمد لله رب العالمين﴾</span></p>
<p>الصَّحَابِيُّ الْجَلِيلُ أَبُو هُرَيْرَةَ رَضِيَ اللَّهُ عَنْهُ</p>
"""

# السطر المشكَّل أعلاه هو محكّ النسخ: بلا إصلاح خريطة النسخ يخرج
# ممزَّقاً وفيه حروف لاتينية دخيلة.
VOCALISED = "الصَّحَابِيُّ الْجَلِيلُ أَبُو هُرَيْرَةَ رَضِيَ اللَّهُ عَنْهُ"

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✔ {label}")
    else:
        failed += 1
        print(f"  ✘ {label}  {detail}")


def get(url: str, timeout: float = 10):
    return urllib.request.urlopen(url, timeout=timeout)


def post(url: str, data: bytes, headers: dict, timeout: float = 120):
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def find_port(process: subprocess.Popen, log: Path, offset: int) -> int | None:
    """
    المنفذ يُكتب في السجل؛ قد يختلف عن 7860 لو كان مشغولاً.

    يُقرأ ما بعد offset فقط: قد تكون نسخة أخرى تعمل وتكتب في السجل
    نفسه، فلا يُخلط سطرها بسطرنا.
    """
    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            return None
        if log.is_file():
            with log.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for line in handle:
                    if "الخادم يعمل على" in line:
                        return int(line.rsplit(":", 1)[-1].strip().rstrip("/"))
        time.sleep(0.5)
    return None


def main() -> int:
    exe = Path(sys.argv[1] if len(sys.argv) > 1 else "_dist/masih.exe").resolve()
    if not exe.is_file():
        print(f"الملف التنفيذي غير موجود: {exe}")
        return 2

    import os

    log = Path(os.environ["LOCALAPPDATA"]) / "Masih" / "masih.log"
    offset = log.stat().st_size if log.is_file() else 0

    print(f"\nفحص {exe.name} ({exe.stat().st_size / 1048576:.1f} ميجابايت)\n")
    process = subprocess.Popen([str(exe), "--no-window"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port = find_port(process, log, offset)
        if port is None:
            print("  ✘ لم يُقلع الخادم — راجع السجل")
            print(log.read_text(encoding="utf-8", errors="replace")[-2000:])
            return 1
        base = f"http://127.0.0.1:{port}"
        print(f"  يعمل على المنفذ {port}\n")

        health = json.loads(get(f"{base}/health").read())
        check("‎/health يعرّف نفسه", health.get("app") == "masih", str(health))

        page = get(f"{base}/").read().decode("utf-8")
        check("الواجهة تُقدَّم", "<title>ماسح</title>" in page)
        check("الواجهة لا تطلب شيئاً من الإنترنت",
              "jsdelivr" not in page and "cdn." not in page)

        engine = get(f"{base}/quran-engine.js").read()
        check("محرّك التدقيق مضمَّن", b"QuranEngine" in engine)

        quran = json.loads(get(f"{base}/quran.json").read())
        check("نصّ المصحف مضمَّن كاملاً",
              len(quran) == 114 and sum(len(s["verses"]) for s in quran) == 6236,
              f"{len(quran)} سورة")

        font = get(f"{base}/fonts/AmiriQuran.ttf").read()
        check("خط المصحف مضمَّن", len(font) > 100_000, f"{len(font)} بايت")
        check("الأيقونة مضمَّنة", b"<svg" in get(f"{base}/favicon.svg").read())

        pdf = post(f"{base}/pdf", SHEET.encode("utf-8"),
                   {"Content-Type": "text/html; charset=utf-8", "Origin": base}).read()
        check("يبني ملف PDF", pdf.startswith(b"%PDF-"), f"{len(pdf)} بايت")

        out = exe.parent / "_smoke.pdf"
        out.write_bytes(pdf)
        try:
            from pypdf import PdfReader

            text = PdfReader(str(out)).pages[0].extract_text() or ""
            arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
            check("نصّ الـ PDF قابل للنسخ",
                  "(cid:" not in text and arabic > 15,
                  f"{arabic} حرفاً عربياً: {text[:60]!r}")
            # يُنزع U+FEFF قبل المقارنة: نضعه بديلاً صامتاً عن السطر
            # الفارغ في خريطة النسخ، وهو صفريّ العرض يذهب عند اللصق.
            clean = text.replace("﻿", "")
            check("النصّ المشكَّل يخرج كما دخل",
                  VOCALISED in clean,
                  f"لم يُطابق: {clean[:120]!r}")
            # الدخيل ما ظهر في النسخ ولم يكن في الورقة أصلاً — فالنقطة
            # والرقم قد يكونان من صلب الوثيقة، وإنما العلّة ما اختُرع.
            source = {c for c in re.sub(r"<[^>]*>", " ", SHEET)
                      if c.isascii() and not c.isspace()}
            intruders = sorted({c for c in text
                                if c.isascii() and not c.isspace()} - source)
            check("لا حروف لاتينية دخيلة في النسخ",
                  not intruders, f"دخلت: {intruders}")
        except ImportError:
            print("  ~ pypdf غير مثبَّت، تُخطّى قراءة النص")
        finally:
            out.unlink(missing_ok=True)

        try:
            post(f"{base}/pdf", b"<p>x</p>", {"Origin": "https://evil.example"})
            check("يرفض الطلب من أصل أجنبي", False, "قُبل الطلب!")
        except urllib.error.HTTPError as exc:
            check("يرفض الطلب من أصل أجنبي", exc.code == 403, f"رمز {exc.code}")

        # إغلاق النافذة ينهي البرنامج — بعد مهلة قصيرة تكفي نافذةً أخرى
        post(f"{base}/bye", b"", {"Origin": base})
        for _ in range(120):
            if process.poll() is not None:
                break
            time.sleep(0.5)
        check("ينتهي عند إغلاق النافذة", process.poll() is not None,
              "ما زال يعمل بعد دقيقة")
    finally:
        if process.poll() is None:
            process.kill()

    print(f"\nنجح {passed} · فشل {failed}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
