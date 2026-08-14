# -*- mode: python ; coding: utf-8 -*-
"""
وصفة بناء masih.exe — ملف واحد، بلا نافذة أوامر، وكلّ شيء بداخله.

    pyinstaller masih.spec --noconfirm

الموارد (الواجهة، نصّ المصحف، الخطوط) تُوضَع في مجلد assets داخل
الحزمة، وهو ما تبحث فيه masih.assets_dir() عبر sys._MEIPASS.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
ASSETS = ROOT / "src" / "masih" / "assets"

# كل مورد بمساره النسبي، فتُحفظ بنية المجلدات داخل الحزمة
datas = [
    (str(path), str(Path("assets") / path.relative_to(ASSETS).parent))
    for path in ASSETS.rglob("*")
    if path.is_file()
]

binaries = []
hiddenimports = ["uharfbuzz", "masih", "masih.server", "masih.pdfbuild",
                 "masih.fonts", "masih.window"]

# النافذة الأصيلة: pywebview يستورد صدفته وقت التشغيل بالاسم لا
# بالتصريح، ويقرأ ملفات .js و.dll من مجلده — فلا يكفي تتبّع
# الاستيرادات، بل تُجمع الحزم كاملة. ونقصُ ملفٍ واحد منها يظهر عند
# المستخدم صندوقَ خطأ خفيّاً يعلّق البرنامج، لا رسالةً في طرفية.
for package in ("webview", "clr_loader", "pythonnet"):
    extra_datas, extra_binaries, extra_hidden = collect_all(package)
    datas += extra_datas
    binaries += extra_binaries
    hiddenimports += extra_hidden

# مكتبات ضخمة لا يستعملها البرنامج وقت التشغيل:
#   pdfplumber/pypdfium2  فحص بصري في الاختبارات فقط
#   tkinter               النافذة WebView2 عبر WinForms، لا Tk
# وصدفات pywebview لأنظمة أخرى: يجمعها collect_all كلها، وهي على
# ويندوز حِمل ميت واستيرادات مفقودة تُغرق سجلّ البناء بالتحذيرات.
excludes = [
    "pdfplumber", "pypdfium2", "tkinter",
    "numpy", "pandas", "matplotlib", "scipy", "pytest",
    "IPython", "notebook",
    "gi", "gtk", "qtpy", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "cefpython3", "objc", "AppKit", "Foundation", "WebKit", "Quartz",
    "jnius", "android",
]

a = Analysis(
    # لا توجّهه إلى src/masih/__main__.py: يُشغَّل عندها كسكربت مستقل
    # فتنكسر استيراداته النسبية. راجع التعليق في run_masih.py.
    ["run_masih.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="masih",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # لا نافذة أوامر — هذا هو المقصود كلّه
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "masih.ico"),
    version=None,
)
