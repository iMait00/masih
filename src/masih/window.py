"""
النافذة: صدَفة ويندوز أصيلة فوق محرّك WebView2، لا متصفّح مموّه.

كان البرنامج يُفتح بـ ‎msedge --app=URL. تلك النافذة بلا شريط عنوان،
لكنها تبقى متصفّحاً في كل ما عداه: النقر الأيمن يفتح قائمة المتصفّح،
وCtrl+F يفتح شريط بحثه فوق بحث البرنامج نفسه، والأيقونة في شريط المهام
أيقونة Edge. فيرى المستخدم موقعاً مفتوحاً لا برنامجاً بين يديه.

فصارت النافذة نافذة ويندوز حقيقية: عنوانها «ماسح» وأيقونتها أيقونتنا،
وقوائم المتصفّح ومفاتيحه مُطفأة من إعدادات WebView2 نفسها — أي في
المضيف قبل أن يصل المفتاح إلى الصفحة، لا بحيلة داخلها. ومحرّك العرض هو
محرّك Edge نفسه، فالواجهة تعمل كما كانت حرفاً بحرف.

وWebView2 قد يغيب عن جهاز، فبقي طريق Edge/Chrome ‎--app احتياطاً: أن
يعمل البرنامج ناقصاً خير من ألّا يعمل.

تنبيه لمن يقرأ لاحقاً: مخزن الصفحة (localStorage) في النافذة الأصيلة
مجلدٌ خاص بالبرنامج لا الملف الشخصي لـ Edge. فوثائق من استعمل النسخة
القديمة تبقى في مخزن Edge ولا تظهر هنا، وتُستعاد بفتح العنوان نفسه في
Edge ونسخها. وهذا ثمن الخروج من المتصفّح، يُدفع مرة واحدة.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import app_dir, asset

log = logging.getLogger("masih")

TITLE = "ماسح"
WINDOW_SIZE = (1280, 860)
MIN_SIZE = (900, 600)

# معرّف WebView2 Evergreen في سجلّ ويندوز
_RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# هوية البرنامج في شريط المهام. ثابتة عمداً: تغييرها يُفقد المستخدم
# اختصاره المثبَّت.
APP_ID = "Masih.Scanner.1"

# خصائص WebView2 التي تُطفأ. كلّها في المضيف، فلا تحتاج الصفحة أن تتعاون.
_MUTED = (
    # قائمة النقر الأيمن كلّها: «رجوع» و«إعادة تحميل» و«فحص العنصر»
    # أوامرُ متصفّح لا أوامرُ ماسح، ووجودها وحده يقول للمستخدم «أنت في
    # متصفّح».
    "AreDefaultContextMenusEnabled",
    # مفاتيح المتصفّح: Ctrl+F وCtrl+P وCtrl+R وF5 وF12 وأخواتها. النسخ
    # واللصق والتحديد والتراجع ليست منها فتبقى تعمل — البرنامج محرّر نصّ
    # قبل كل شيء. والمفتاح يصل إلى الصفحة كما هو، فبحث البرنامج الداخلي
    # على Ctrl+F يبقى حيّاً بينما يختفي شريط بحث المتصفّح.
    "AreBrowserAcceleratorKeysEnabled",
    "AreDevToolsEnabled",
    # الشريط الذي يطلّ أسفل النافذة بعنوان الرابط عند مرور المؤشر
    "IsStatusBarEnabled",
    # التمرير الجانبي بإصبعين يعود بالصفحة إلى الخلف — ولا خلفَ في برنامج
    "IsSwipeNavigationEnabled",
    # في الواجهة حقل مفتاح API، وعرضُ متصفّحٍ حفظَه يفضح أن ما تحته متصفّح
    "IsGeneralAutofillEnabled",
    "IsPasswordAutosaveEnabled",
)

# حَرَسٌ يُحقن في الصفحة عند كل تحميل. إعدادات WebView2 أعلاه هي الحاسمة،
# وهذا احتياطٌ لو غابت خاصية عن نسخة أقدم من زمن التشغيل: تبقى الصفحة
# محميّة، وإن نجحت الإعدادات لم يضرّ التكرار.
_GUARD_JS = r"""
(function () {
  if (window.__masihShell) { return "قائم"; }
  window.__masihShell = true;

  document.addEventListener("contextmenu", function (e) {
    e.preventDefault();
  }, true);

  /* الاعتماد على e.code لا e.key: لوحة المفاتيح هنا عربية غالباً،
     فحرف مفتاح F يصل "ب" لا "f" — والمقارنة بالحرف تُفلت المفتاح. أما
     e.code فاسم الزرّ في اللوحة، لا يتغيّر بتغيّر اللغة. */
  var CODE = { KeyF:1, KeyG:1, KeyH:1, KeyJ:1, KeyO:1, KeyP:1, KeyR:1,
               KeyS:1, KeyU:1 };
  var LETTER = { f:1, g:1, h:1, j:1, o:1, p:1, r:1, s:1, u:1 };
  var DEVTOOLS = { KeyI:1, KeyJ:1, KeyC:1 };
  var BARE = { F3:1, F5:1, F7:1, F12:1 };

  /* preventDefault وحدها بلا stopPropagation: الواجهة نفسها تربط Ctrl+F
     ببحثها الداخلي، فابتلاعُ الحدث يقتل بحث البرنامج مع بحث المتصفّح.
     المطلوب منع تصرّف المتصفّح لا منع وصول المفتاح. */
  document.addEventListener("keydown", function (e) {
    var code = e.code || "";
    var key = (e.key || "").toLowerCase();
    var mod = (e.ctrlKey || e.metaKey) && !e.altKey;
    if (mod && e.shiftKey && DEVTOOLS[code] === 1) { e.preventDefault(); return; }
    if (mod && !e.shiftKey && (CODE[code] === 1 || LETTER[key] === 1)) {
      e.preventDefault();
      return;
    }
    if (BARE[e.key] === 1) { e.preventDefault(); }
  }, true);

  return "مثبَّت";
})();
"""

# النافذة الأصيلة الحيّة، إن وُجدت
_active = None


# ============================================================ التهيئة
def webview2_installed() -> bool:
    """
    هل زمن تشغيل WebView2 مثبَّت؟

    يُسأل السؤال قبل استيراد pywebview لا بعده: pywebview حين لا يجد
    WebView2 يرتدّ إلى محرّك Internet Explorer القديم، ويكتب مفاتيح في
    سجلّ ويندوز ليُفعّله. محرّكٌ لا يفهم واجهتنا، وأثرٌ في جهاز المستخدم
    لا مبرّر له. فإن غاب WebView2 لم نستورد pywebview أصلاً.
    """
    if sys.platform != "win32":
        return False
    import winreg

    places = [
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}"),
        (winreg.HKEY_CURRENT_USER,
         rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_RUNTIME_GUID}"),
    ]
    for root, path in places:
        try:
            with winreg.OpenKey(root, path) as key:
                version = str(winreg.QueryValueEx(key, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            log.info("زمن تشغيل WebView2 %s", version)
            return True
    return False


def _claim_taskbar_identity() -> None:
    """
    هوية مستقلة في شريط المهام.

    بلا معرّف خاص يُلحق ويندوز نافذتنا بالبرنامج الذي أطلقها — بـ
    python.exe عند التطوير، أو بمجموعة أخرى — فتظهر أيقونة ليست لنا،
    ولا يثبت الاختصار على البرنامج الصحيح.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as exc:  # noqa: BLE001
        log.debug("تعذّر تثبيت هوية شريط المهام: %s", exc)


def _data_dir() -> Path:
    """مجلد بيانات البرنامج عند المستخدم — قصير المسار ودائم."""
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "Masih" if base else app_dir()


def _storage_dir() -> str:
    """
    مجلد بيانات الصفحة — يجب أن يكون ثابتاً.

    فيه localStorage: وثائق المستخدم وتفضيلاته ومفتاحه. مجلد مؤقت (وهو
    ما يختاره pywebview افتراضاً في الوضع الخاص) يعني ضياع كل ذلك عند
    كل إغلاق.
    """
    folder = _data_dir() / "webview"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


# ويندوز يحمّل ملفات الأيقونات بواجهة قديمة تقف عند ٢٦٠ محرفاً
_MAX_PATH = 250


def _icon_path() -> str | None:
    """
    مسار الأيقونة، قصيراً بالضرورة.

    تحميل أيقونة من مسار أطول من ٢٦٠ محرفاً يرمي استثناءً في خيط
    النافذة، لا يمرّ ببايثون فلا يُمسك: يموت البرنامج بلا رسالة. وذلك
    وارد — مستودعٌ في مسار عميق، أو مجلد فكّ مؤقت طويل. فإن طال المسار
    نُسخت الأيقونة إلى مجلد بيانات البرنامج وأُعطي مسارها القصير.

    وإن تعذّر ذلك أيضاً فلا أيقونة منّا: يأخذها pywebview عندئذ من
    masih.exe نفسه — وهي أيقونتنا كذلك.
    """
    source = asset("masih.ico")
    if not source.is_file():
        return None
    if len(str(source)) < _MAX_PATH:
        return str(source)
    try:
        folder = _data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "masih.ico"
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            target.write_bytes(source.read_bytes())
        if len(str(target)) < _MAX_PATH:
            return str(target)
    except OSError as exc:
        log.warning("تعذّر تقصير مسار الأيقونة: %s", exc)
    return None


# ============================================================ النافذة الأصيلة
def _mute_browser(window) -> list[str]:
    """يُطفئ خصائص المتصفّح في WebView2. يُرجع أسماء ما تعذّر إطفاؤه."""
    from System import Func, Type
    from webview.platforms import winforms

    form = winforms.BrowserView.instances[window.uid]
    missed: list[str] = []

    def apply():
        settings = form.browser.webview.CoreWebView2.Settings
        for name in _MUTED:
            try:
                setattr(settings, name, False)
            except Exception:  # noqa: BLE001 - خاصية غائبة عن نسخة أقدم
                missed.append(name)
        return None

    # كائنات WebView2 تعيش في خيط النافذة وحده، وحدث loaded يصل في خيط
    # جانبي، فيُمرَّر العمل إلى هناك.
    form.Invoke(Func[Type](apply))
    return missed


def _harden(window) -> None:
    """يُنزع عن النافذة كل ما يجعلها تبدو متصفّحاً، عند كل تحميل."""
    try:
        missed = _mute_browser(window)
        if missed:
            log.warning("خصائص WebView2 لم تُطفأ: %s", "، ".join(missed))
        else:
            log.info("أُطفئت قوائم المتصفّح ومفاتيحه")
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر ضبط إعدادات WebView2 (%s) — يبقى حَرَس الصفحة", exc)
    try:
        window.evaluate_js(_GUARD_JS)
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر حقن حَرَس الصفحة: %s", exc)


def _open_native(url: str, on_close) -> bool:
    """
    يفتح النافذة الأصيلة ويحجز الخيط حتى تُغلق.

    يُرجع False قبل أن يفتح شيئاً إن تعذّر ذلك، ليتولّى الاحتياطيُّ الأمر.
    """
    global _active

    if not webview2_installed():
        log.info("زمن تشغيل WebView2 غير مثبَّت")
        return False
    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        log.warning("pywebview غير متاح: %s", exc)
        return False

    # التصدير في الواجهة روابط blob تُنزَّل؛ ومنع التنزيل (وهو الافتراضي
    # في pywebview) يُسقط تصدير PDF وDOCX وMarkdown صامتاً بلا رسالة.
    webview.settings["ALLOW_DOWNLOADS"] = True
    # رابط إلى الخارج يُفتح في متصفّح المستخدم لا داخل نافذتنا: هذه
    # واجهة برنامج، والخروج منها إلى الويب يعيدنا إلى ما هربنا منه.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    _claim_taskbar_identity()
    icon = _icon_path()
    width, height = WINDOW_SIZE

    try:
        window = webview.create_window(
            TITLE, url,
            width=width, height=height, min_size=MIN_SIZE,
            resizable=True,
            # الافتراضي في pywebview يمنع تحديد النصّ بحقن CSS، وهو خراب
            # في برنامج قوامه نصّ يُنسخ.
            text_select=True,
            # تكبير الصفحة بـ Ctrl+عجلة يبقى: وثيقة عربية قد تحتاجه.
            zoomable=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر إنشاء النافذة الأصيلة: %s", exc)
        return False

    window.events.loaded += lambda: _harden(window)
    if on_close is not None:
        window.events.closed += on_close

    _active = window
    try:
        webview.start(
            # الوضع الخاص يمحو localStorage عند كل خروج، ووثائق المستخدم
            # فيه. فيُطفأ ويُثبَّت للمخزن مكان معلوم.
            private_mode=False,
            storage_path=_storage_dir(),
            icon=icon,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر تشغيل النافذة الأصيلة: %s", exc)
        return False
    finally:
        _active = None

    log.info("أُغلقت النافذة")
    return True


def native_alive() -> bool:
    """هل هناك نافذة أصيلة مفتوحة الآن؟"""
    return _active is not None


def pick_folder(start: str = "") -> str | None:
    """
    يفتح مختار المجلدات الأصيل. يُرجع المسار المختار، أو None إن أُلغي.

    يرمي RuntimeError إن لم تكن هناك نافذة أصيلة — وهو الوضع في
    ‎--no-window وفي صدَفة المتصفّح الاحتياطية. لا بديل مصنوعاً هنا:
    حوار ويندوز هو ما يعرفه المستخدم، وصنعُ شبيهٍ له في صفحة يعطي
    مستعرض ملفات أعرج لا يرى الأقراص ولا الشبكة.

    والنداء يجري في خيط الطلب، وpywebview يمرّره بنفسه إلى خيط النافذة
    وينتظر. فيُحجَز خيط الطلب وحده حتى يُغلق الحوار، والخادم يخدم كل
    اتصال في خيط مستقل، فلا يتوقّف شيء آخر.
    """
    window = _active
    if window is None:
        raise RuntimeError("لا توجد نافذة أصيلة مفتوحة")
    import webview

    # pywebview 6 نقل الثابت إلى FileDialog.FOLDER وأبقى القديم يطبع
    # تحذير إهمال في كل نداء. فيُؤخذ الجديد إن وُجد، والقديم لمن كان
    # على نسخة أقدم.
    dialogs = getattr(webview, "FileDialog", None)
    folder_dialog = getattr(dialogs, "FOLDER", None)
    if folder_dialog is None:
        folder_dialog = webview.FOLDER_DIALOG

    chosen = window.create_file_dialog(folder_dialog, directory=start or "")
    if not chosen:
        return None
    if isinstance(chosen, (list, tuple)):
        return str(chosen[0]) if chosen else None
    return str(chosen)


def close_window() -> None:
    """يغلق النافذة الأصيلة إن كانت مفتوحة — لا نافذةَ حيّةً بلا خادم."""
    window = _active
    if window is None:
        return
    try:
        window.destroy()
    except Exception as exc:  # noqa: BLE001
        log.warning("تعذّر إغلاق النافذة: %s", exc)


# ============================================================ الاحتياطي
def _candidates() -> list[Path]:
    """مسارات Edge و Chrome المحتملة، بترتيب الأفضلية."""
    names = [
        (r"Microsoft\Edge\Application\msedge.exe",),
        (r"Google\Chrome\Application\chrome.exe",),
    ]
    roots = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
             os.environ.get("LOCALAPPDATA")]
    found: list[Path] = []
    for (rel,) in names:
        for root in roots:
            if not root:
                continue
            path = Path(root) / rel
            if path.is_file():
                found.append(path)
    return found


def _launch_flags(url: str) -> list[str]:
    width, height = WINDOW_SIZE
    return [
        f"--app={url}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _open_external(url: str) -> bool:
    """
    الطريق القديم: نافذة متصفّح مجرَّدة من شريط العنوان.

    لا يُمرَّر ‎--user-data-dir عمداً: مخزن المتصفح (وفيه وثائق المستخدم
    المحفوظة ومفتاحه) مربوط بالملف الشخصي الافتراضي، وعزله يُخفيها عنه.
    """
    for browser in _candidates():
        try:
            flags = {}
            if sys.platform == "win32":
                # لا نافذة أوامر خلف المتصفح
                flags["creationflags"] = (subprocess.DETACHED_PROCESS
                                          | subprocess.CREATE_NO_WINDOW)
            subprocess.Popen([str(browser), *_launch_flags(url)],
                             close_fds=True, **flags)
            log.info("فُتحت النافذة عبر %s", browser.name)
            return True
        except OSError as exc:
            log.warning("تعذّر تشغيل %s: %s", browser.name, exc)

    log.info("لم يُعثر على Edge أو Chrome — يُفتح المتصفح الافتراضي")
    try:
        webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        log.error("تعذّر فتح المتصفح: %s", exc)
    return False


# ============================================================ الواجهة
def open_window(url: str, on_close=None) -> bool:
    """
    يفتح واجهة البرنامج. يُرجع True إن كانت النافذة أصيلة.

    وTrue تعني أيضاً أن الاستدعاء حجز الخيط حتى أُغلقت النافذة: حلقة
    رسائل ويندوز لا تعمل إلا في الخيط الرئيسي. أما False فتعني أن
    الواجهة سُلّمت إلى متصفّح في عملية أخرى وعاد الاستدعاء فوراً، فعلى
    المنادي أن ينتظر الخادم بنفسه.
    """
    if _open_native(url, on_close):
        return True
    log.info("تعذّرت النافذة الأصيلة — تُفتح صدَفة المتصفّح الاحتياطية")
    _open_external(url)
    return False


def alert(title: str, text: str) -> None:
    """صندوق رسالة على ويندوز — الطريقة الوحيدة للكلام بلا نافذة أوامر."""
    if sys.platform != "win32":
        print(f"{title}: {text}", file=sys.stderr)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:  # noqa: BLE001
        pass
