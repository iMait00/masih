"""
ماسح — يحوّل الوثائق الممسوحة إلى نصّ عربي سليم قابل للنسخ، ويدقّق آياته.

الحزمة كلها تعمل بلا إنترنت: نصّ المصحف والخطوط مضمَّنة داخل البرنامج.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"
__all__ = ["__version__", "assets_dir", "asset", "app_dir"]


def app_dir() -> Path:
    """المجلد الذي يجلس فيه البرنامج — بجانب الـ exe، أو جذر المستودع."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    """
    مجلد الموارد المضمَّنة.

    داخل ملف exe مبنيّ بـ PyInstaller تُفكّ الموارد في مجلد مؤقت يشير
    إليه sys._MEIPASS. وخارجه تُقرأ من مكانها في المستودع.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parent / "assets"


def asset(*parts: str) -> Path:
    """مسار مورد مضمَّن، مثل asset('fonts', 'AmiriQuran.ttf')."""
    return assets_dir().joinpath(*parts)
