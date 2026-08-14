"""
العثور على ملفات الخطوط اللازمة لبناء الـ PDF.

يبحث في مجلد الموارد المضمَّن أولاً، ثم في خطوط النظام. الترتيب مقصود:
خطّا Amiri و Amiri Quran مرفقان مع البرنامج، فلا يعتمد إخراج الـ PDF على
ما هو مثبَّت على الجهاز. وهذا يعني أن الملف يخرج بالشكل نفسه على أي حاسوب.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from . import asset, assets_dir

# أسماء ملفات كل عائلة، بترتيب الأفضلية.
REGULAR: dict[str, list[str]] = {
    "amiri quran": ["AmiriQuran.ttf", "AmiriQuran-Regular.ttf"],
    "amiri": ["Amiri-Regular.ttf"],
    "traditional arabic": ["trado.ttf", "TraditionalArabic.ttf"],
    "simplified arabic": ["simpo.ttf"],
    "sakkal majalla": ["majalla.ttf"],
    "scheherazade new": ["ScheherazadeNew-Regular.ttf"],
    "cairo": ["Cairo-Regular.ttf"],
    "arial": ["arial.ttf"],
    "tahoma": ["tahoma.ttf"],
    "segoe ui": ["segoeui.ttf"],
}

BOLD: dict[str, list[str]] = {
    "amiri quran": ["AmiriQuran.ttf"],  # لا توجد نسخة عريضة؛ يُستعمل العادي
    "amiri": ["Amiri-Bold.ttf"],
    "traditional arabic": ["tradbdo.ttf"],
    "sakkal majalla": ["majallab.ttf"],
    "scheherazade new": ["ScheherazadeNew-Bold.ttf"],
    "cairo": ["Cairo-Bold.ttf"],
    "arial": ["arialbd.ttf"],
    "tahoma": ["tahomabd.ttf"],
    "segoe ui": ["segoeuib.ttf"],
}

# يُجرَّب بالترتيب حين لا تُوجد العائلة المطلوبة. Amiri أولاً لأنه مرفق.
FALLBACK_REGULAR = ["Amiri-Regular.ttf", "trado.ttf", "arial.ttf",
                    "tahoma.ttf", "segoeui.ttf", "DejaVuSans.ttf"]
FALLBACK_BOLD = ["Amiri-Bold.ttf", "tradbdo.ttf", "arialbd.ttf",
                 "tahomabd.ttf", "segoeuib.ttf"]


def _search_roots() -> list[Path]:
    """مجلدات البحث: الموارد المضمَّنة، ثم خطوط النظام والمستخدم."""
    roots = [assets_dir() / "fonts"]
    windir = os.environ.get("WINDIR")
    if windir:
        roots.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    roots += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
              Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    return roots


def _locate(filename: str) -> Path | None:
    for root in _search_roots():
        if not root.is_dir():
            continue
        direct = root / filename
        if direct.is_file():
            return direct
        # بعض الأنظمة ترتّب الخطوط في مجلدات فرعية
        try:
            for hit in root.rglob(filename):
                if hit.is_file():
                    return hit
        except OSError:
            continue
    return None


@lru_cache(maxsize=64)
def find_font(family: str, bold: bool = False) -> Path | None:
    """
    يُرجع مسار ملف خط للعائلة المطلوبة، أو أقرب بديل متاح.

    يُرجع None فقط إذا لم يوجد أي خط عربي على الإطلاق — وهو ما لا يحدث
    عملياً لأن Amiri مرفق مع البرنامج.
    """
    key = (family or "").strip().strip("\"'").lower()
    table = BOLD if bold else REGULAR
    fallback = FALLBACK_BOLD if bold else FALLBACK_REGULAR

    for name in table.get(key, []) + fallback:
        found = _locate(name)
        if found:
            return found

    # العريض غير موجود: العادي خير من لا شيء
    if bold:
        return find_font(family, bold=False)
    return None


def quran_font() -> Path | None:
    """خط الرسم العثماني — مضمَّن دائماً، فلا يفشل."""
    return asset("fonts", "AmiriQuran.ttf") if asset(
        "fonts", "AmiriQuran.ttf").is_file() else find_font("amiri quran")


def describe() -> str:
    """سطر تشخيصي يُكتب في السجل عند الإقلاع."""
    body = find_font("Traditional Arabic")
    quran = quran_font()
    return (f"body={body.name if body else 'MISSING'} "
            f"quran={quran.name if quran else 'MISSING'}")
