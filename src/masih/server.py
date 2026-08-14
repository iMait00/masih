"""
خادم محلي على 127.0.0.1 يقدّم الواجهة ويبني ملفات الـ PDF.

الواجهة تُقدَّم من الخادم نفسه، فالصفحة والخادم مصدر واحد (same origin).
وهذا يحلّ ثلاث مشكلات دفعة واحدة:
    • لا حاجة لترويسات CORS مفتوحة على المنفذ المحلي
    • طلب المسح الضوئي يمرّ عبر /ocr فلا يعترضه المتصفح
    • نصّ المصحف والخطوط تُقدَّم محلياً، فالبرنامج يعمل بلا إنترنت

المنفذ 7860 ليس اعتباطياً: مخزن المتصفح (localStorage) مربوط بالأصل
http://127.0.0.1:7860، فتغييره يُخفي وثائق المستخدم المحفوظة سابقاً.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import __version__, app_dir, asset
from .pdfbuild import MissingDependency, build_pdf, selectable_report

log = logging.getLogger("masih")

DEFAULT_PORT = 7860
HOST = "127.0.0.1"

# نقطة النهاية الوحيدة المسموح بتمرير الطلبات إليها. تثبيتها هنا يمنع
# استعمال الخادم المحلي وسيطاً مفتوحاً لأي عنوان.
MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"

MAX_UPLOAD = 60 * 1024 * 1024        # حدّ الـ API نحو ٥٠ ميجابايت
MAX_SHEET = 32 * 1024 * 1024
OCR_TIMEOUT = 300

MIME = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".js": "text/javascript; charset=utf-8",
}

# ملفّا الحالة في مجلد بيانات المستخدم — لا بجانب الـ exe: قد يجلس في
# مجلد لا يملك المستخدم حقّ الكتابة فيه، فتفشل الكتابة صامتة.
SETTINGS_FILE = "settings.json"
SESSIONS_FILE = "sessions.json"

MAX_JSON = 64 * 1024            # الإعدادات و/reveal أجسامها صغيرة
MAX_STEM = 80                   # أقصى طول لاسم الملف المشتقّ من العنوان

# ملفّ ‎PDF‎ لكتابٍ مصوَّر قد يبلغ عدّة ميجابايتات، والبيانات تصل
# مُرمَّزة بـ base64 فتنتفخ الثلث. فحدٌّ مستقلّ أوسعُ من ‎MAX_JSON‎
# بكثير، ومع ذلك مقطوعٌ به لئلّا تُملأ الذاكرة بجسمٍ لا آخر له.
MAX_SAVE = 96 * 1024 * 1024

# امتدادات ما يُصدَّر. القائمة مغلقة عمداً: الاسم يصل من الواجهة،
# فلو تُرك الامتداد حرّاً لأمكن كتابة ‎.bat‎ أو ‎.lnk‎ في مجلد
# المستخدم — والمجلد مجلد تنزيلات يفتحه بلا ريبة.
SAVE_KINDS = {"pdf": ".pdf", "docx": ".docx", "md": ".md"}

# كل تعديل على الفهرس قراءةٌ فتغييرٌ فكتابة. ولولا القفل لضاع تعديلٌ حين
# يحفظ المستخدم كتابين في اللحظة نفسها — والخادم يخدم كل طلب في خيط.
_store_lock = threading.RLock()

# حوارٌ أصيل واحد في المرة. نافذتان معاً تحجب إحداهما الأخرى فتبدو
# الواجهة معلّقة، والمستخدم لا يرى إلا نافذةً لا تستجيب.
_picker_lock = threading.Lock()


# ==================================================== مجلد البيانات والحفظ
def data_dir() -> Path:
    """
    مجلد بيانات البرنامج — نفسه الذي يجلس فيه ملف السجل.

    يُقرأ من البيئة في كل نداء ولا يُحفَظ في متغيّر: الاختبارات تحوّله
    إلى مجلد مؤقت، وحفظُه مرةً واحدة كان يجعلها تكتب في مجلد المستخدم.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    folder = Path(base) / "Masih" if base else app_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return app_dir()
    return folder


# معرّف مجلد التنزيلات في قائمة مجلدات ويندوز المعروفة (FOLDERID_Downloads)
_FOLDERID_DOWNLOADS = (0x374DE290, 0x123F, 0x4565,
                       (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))


def _shell_downloads() -> Path | None:
    """
    مجلد التنزيلات كما تعرفه صدَفة ويندوز نفسها.

    ولا يكفي تخمين %USERPROFILE%\\Downloads: المستخدم قد ينقل مجلد
    التنزيلات إلى قرص آخر — وهو شائع حين يمتلئ قرص النظام — فيبقى
    المسار المخمَّن مجلداً فارغاً لا يفتحه أحد، ويقول المستخدم إن
    البرنامج «يبتلع» كتبه.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        first, second, third, tail = _FOLDERID_DOWNLOADS
        guid = _GUID(first, second, third, (ctypes.c_ubyte * 8)(*tail))
        out = ctypes.c_wchar_p()
        status = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(out))
        if status != 0 or not out.value:
            return None
        try:
            # يُنسخ النصّ إلى Path قبل تحرير الذاكرة، لا بعده
            return Path(out.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception as exc:  # noqa: BLE001 - غياب ctypes أو نداء فاشل
        log.debug("تعذّر سؤال الصدَفة عن مجلد التنزيلات: %s", exc)
        return None


def default_save_dir() -> Path:
    """مجلد الحفظ الافتراضي: التنزيلات، ويُنشأ إن لم يكن موجوداً."""
    path = _shell_downloads()
    if path is None:
        home = os.environ.get("USERPROFILE") or str(Path.home())
        path = Path(home) / "Downloads"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("تعذّر تهيئة مجلد التنزيلات %s: %s", path, exc)
    return path


def check_dir(raw: str) -> tuple[Path | None, str]:
    """
    يفحص مسار حفظ اقترحه المستخدم. يُرجع (المسار، "") أو (None، سبب الرفض).

    الفحص بكتابة ملف فعليّ لا بـ os.access: صلاحيات ويندوز تمرّ بقوائم
    تحكّم لا تفهمها os.access، فتقول «تستطيع الكتابة» ثم تفشل الكتابة
    عند أول كتاب — وقد ضاع عمل المستخدم.
    """
    text = (raw or "").strip().strip('"')
    if not text:
        return None, "لم يصل أي مسار"
    try:
        path = Path(os.path.expandvars(text)).expanduser()
    except (OSError, ValueError):
        return None, "المسار غير صالح"
    if not path.is_absolute():
        return None, "اكتب مساراً كاملاً يبدأ باسم القرص، مثل D:\\كتبي"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"تعذّر إنشاء المجلد: {exc.strerror or exc}"
    if not path.is_dir():
        return None, "المسار موجود وليس مجلداً"
    probe = path / f".masih-{uuid.uuid4().hex[:8]}.tmp"
    try:
        probe.write_bytes(b"masih")
        probe.unlink()
    except OSError as exc:
        return None, f"لا يمكن الكتابة في هذا المجلد: {exc.strerror or exc}"
    return path.resolve(), ""


def read_settings() -> dict:
    try:
        data = json.loads((data_dir() / SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(data: dict) -> None:
    atomic_write(data_dir() / SETTINGS_FILE,
                 json.dumps(data, ensure_ascii=False, indent=2))


def save_dir() -> Path:
    """
    مجلد الحفظ الفعّال.

    يُعاد فحص المحفوظ في كل نداء لا يُصدَّق على علّاته: المستخدم قد يختار
    مجلداً على قرص خارجي ثم ينزعه، فالسقوط إلى التنزيلات خيرٌ من عطل
    عند الحفظ.
    """
    stored = read_settings().get("saveDir")
    if isinstance(stored, str) and stored.strip():
        path, why = check_dir(stored)
        if path is not None:
            return path
        log.warning("مسار الحفظ المحفوظ لم يعد صالحاً (%s) — يُستعمل الافتراضي", why)
    return default_save_dir()


def atomic_write(path: Path, text: str) -> None:
    """
    كتابة لا تُبتَر.

    الكتابة المباشرة تقصّ الملف أولاً ثم تملؤه، فانقطاعٌ بينهما يترك
    كتاب المستخدم مبتوراً أو فارغاً. فيُكتب إلى ملف مؤقت في المجلد نفسه
    ثم يحلّ محلّ الأصل بنقلةٍ واحدة لا تنقسم (os.replace).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=str(path.parent),
        prefix=".masih-", suffix=".tmp", delete=False)
    try:
        with handle as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, blob: bytes) -> None:
    """
    كـ ‎atomic_write‎ سواء، غير أنها لا تمرّ بالنصّ.

    ملفّا الـ PDF والـ docx بايتاتٌ صرفة، وأي دورةٍ على ‎str‎ —
    فكّ ترميزٍ ثم إعادته — تُفسدها إفساداً لا يُرى إلا عند الفتح:
    يقول وورد إن الملف تالف والمستخدم يظنّ البرنامج كتبه ناقصاً.
    فتُكتب البايتات كما هي، ثم تحلّ محلّ الأصل بنقلةٍ واحدة.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=str(path.parent), prefix=".masih-", suffix=".tmp",
        delete=False)
    try:
        with handle as out:
            out.write(blob)
            out.flush()
            os.fsync(out.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


# ==================================================== أسماء الملفات
# أسماء أجهزة محجوزة في ويندوز منذ DOS. الملف المسمّى بها يفشل إنشاؤه
# مهما كان امتداده: CON.md محجوز كـ CON.
_RESERVED = ({"CON", "PRN", "AUX", "NUL", "CLOCK$"}
             | {f"COM{i}" for i in range(1, 10)}
             | {f"LPT{i}" for i in range(1, 10)})

# فواصل المسار ومحارف ويندوز الممنوعة ومحارف التحكّم
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_stem(title: str) -> str:
    """
    اسم ملف من عنوان الكتاب.

    العنوان يكتبه المستخدم — أو يصل من نصّ ممسوح — فقد يحمل فواصل مسار
    أو «..» فيخرج الملف من مجلد الحفظ إلى حيث لا ينبغي. وويندوز يقصّ
    النقط والفراغات الأخيرة صامتاً، فـ «كتاب.» يصير «كتاب» وقد ظننّا
    الاسمين مختلفين.
    """
    name = _BAD_CHARS.sub(" ", title or "")
    name = name.replace("..", " ")
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(". ")
    name = name[:MAX_STEM].strip(". ")
    if not name:
        name = "كتاب"
    if name.upper() in _RESERVED or name.upper().split(".")[0] in _RESERVED:
        name = "_" + name
    return name


def unique_md_path(folder: Path, title: str, taken: set[str]) -> Path:
    """
    مسار ملف ‎.md لم يُؤخذ بعد داخل مجلد الحفظ.

    كتابان بالعنوان نفسه لا يجوز أن يدوس أحدهما الآخر، فيُلحق بالثاني
    رقم. والاحتواء يُتحقَّق منه بمقارنة المسار بعد الحلّ لا بالنظر إلى
    الاسم: هذا هو الحاجز الأخير أمام عنوان معادٍ.
    """
    stem = safe_stem(title)
    root = folder.resolve()
    for attempt in range(1, 1000):
        name = f"{stem}.md" if attempt == 1 else f"{stem} ({attempt}).md"
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target.parent != root:
            raise ValueError("اسم الملف يخرج من مجلد الحفظ")
        if name.lower() in taken or target.exists():
            continue
        return target
    raise ValueError("تعذّر إيجاد اسم ملف متاح")


def unique_export_path(folder: Path, title: str, suffix: str) -> Path:
    """
    مسارُ ملفٍّ مُصدَّر لم يُؤخذ بعد داخل مجلد الحفظ — لأي امتداد.

    وهي ‎unique_md_path‎ نفسها في انضباطها، غير أن الامتداد يأتي من
    قائمة مغلقة عندنا لا من الواجهة: الاسم يكتبه المستخدم أو يجيء
    من عنوانٍ ممسوح، فيُنقّى بـ ‎safe_stem‎ حتى لا يبقى فيه فاصلُ
    مسارٍ ولا «..»، ثم يُقارَن المسارُ بعد الحلّ بجذر المجلد — وهذا
    هو الحاجز الأخير: ما لم يكن أباً مباشراً للملف رُفض الاسم كلّه،
    فلا وصلةٌ رمزية ولا اسمٌ معادٍ يُخرج الكتابة من المجلد.
    """
    stem = safe_stem(title)
    root = folder.resolve()
    for attempt in range(1, 1000):
        name = f"{stem}{suffix}" if attempt == 1 else f"{stem} ({attempt}){suffix}"
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target.parent != root:
            raise ValueError("اسم الملف يخرج من مجلد الحفظ")
        if target.exists():
            continue
        return target
    raise ValueError("تعذّر إيجاد اسم ملف متاح")


def inside_save_dir(raw: str) -> Path | None:
    """
    يُرجع المسار إن كان ملفاً قائماً داخل مجلد الحفظ، وإلا None.

    فتحُ ملفٍّ بنقرةٍ من الواجهة يعني تسليمَه إلى الصدَفة لتشغّله
    بالبرنامج المقترن به. فلو قُبل أيُّ مسار لصار الخادمُ المحليّ
    بابَ تشغيلٍ لأي ملفٍّ على القرص. فلا يُفتح إلا ما كتبناه نحن:
    ملفٌّ — لا مجلد ولا وصلة — أبوه مجلد الحفظ عينه بعد حلّ المسار.
    """
    text = (raw or "").strip().strip('"')
    if not text:
        return None
    try:
        path = Path(os.path.expandvars(text)).expanduser().resolve()
    except (OSError, ValueError):
        return None
    root = save_dir().resolve()
    if not path.is_relative_to(root) or path.parent != root:
        return None
    if not path.is_file():
        return None
    return path


# ==================================================== سجلّ الجلسات
_FIELDS = ("id", "title", "file", "pages", "chars", "created", "updated")
_LOST = "ملف هذه الجلسة لم يعد في مكانه — نُقل أو حُذف من خارج البرنامج"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _index_path() -> Path:
    return data_dir() / SESSIONS_FILE


def load_index() -> list[dict]:
    """فهرس الجلسات. فهرس تالف لا يُسقط البرنامج — يُعامَل معاملة الفارغ."""
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("sessions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("id")]


def store_index(items: list[dict]) -> None:
    atomic_write(_index_path(),
                 json.dumps({"sessions": items}, ensure_ascii=False, indent=2))


def _public(entry: dict) -> dict:
    """
    شكل الجلسة كما تراه الواجهة.

    وإن غاب الملف من مكانه لم يُحذف من الفهرس ولم يُرمَ عطل: تُضاف علامة
    تعرضها الواجهة. الملف ملك المستخدم، وقد يكون نقله لا فقده.
    """
    out = {key: entry.get(key) for key in _FIELDS}
    if not _entry_file(entry).is_file():
        out["missing"] = True
        out["error"] = _LOST
    return out


def _entry_file(entry: dict) -> Path:
    return Path(str(entry.get("file") or "."))


def list_sessions() -> list[dict]:
    with _store_lock:
        items = load_index()
    items.sort(key=lambda item: str(item.get("updated") or ""), reverse=True)
    return [_public(item) for item in items]


def read_session(sid: str) -> dict | None:
    with _store_lock:
        entry = next((i for i in load_index() if i.get("id") == sid), None)
    if entry is None:
        return None
    out = _public(entry)
    try:
        out["markdown"] = _entry_file(entry).read_text(encoding="utf-8")
    except OSError:
        out["markdown"] = ""
        out["missing"] = True
        out["error"] = _LOST
    return out


def save_session(sid: str | None, title: str, markdown: str, pages: int) -> dict:
    """
    ينشئ جلسة أو يحدّثها. يرمي KeyError إن أُعطي معرّفاً لا وجود له.

    ومسار الملف يُختار مرة واحدة عند الإنشاء ثم يثبت: تغييرُه مع كل
    تعديل على العنوان يترك في مجلد المستخدم ملفات يتيمة، أو يعيد تسمية
    ملف قد يكون فتحه في محرّر آخر.
    """
    now = _now()
    title = (title or "").strip() or "كتاب بلا عنوان"
    with _store_lock:
        items = load_index()
        entry = None
        if sid:
            entry = next((i for i in items if i.get("id") == sid), None)
            if entry is None:
                raise KeyError(sid)

        if entry is None:
            entry = {"id": uuid.uuid4().hex[:12], "created": now}
            items.append(entry)
            target = unique_md_path(save_dir(), title, _taken(items))
            entry["file"] = str(target)
        else:
            target = _entry_file(entry)
            # المجلد نفسه اختفى (قرص نُزع، أو غُيّر مسار الحفظ ثم حُذف
            # القديم): يُعطى الكتاب مكاناً جديداً بدل أن يفشل الحفظ.
            if not target.is_absolute() or not target.parent.is_dir():
                target = unique_md_path(save_dir(), title, _taken(items))
                entry["file"] = str(target)

        entry.update({"title": title, "pages": max(0, int(pages or 0)),
                      "chars": len(markdown), "updated": now})
        atomic_write(target, markdown)
        store_index(items)
        log.info("حُفظت جلسة «%s» في %s (%s محرفاً)", title, target, len(markdown))
        return _public(entry)


def _taken(items: list[dict]) -> set[str]:
    return {_entry_file(i).name.lower() for i in items}


def forget_session(sid: str) -> str | None:
    """
    يمحو الجلسة من الفهرس وحده. يُرجع مسار الملف، أو None إن لم تُعرف.

    ملف الـ md لا يُحذف أبداً: هو وثيقة المستخدم لا ملفٌّ من ملفاتنا،
    وحذفه من زرٍّ في قائمة عملٌ لا يُتراجَع عنه.
    """
    with _store_lock:
        items = load_index()
        entry = next((i for i in items if i.get("id") == sid), None)
        if entry is None:
            return None
        items.remove(entry)
        store_index(items)
    return str(entry.get("file") or "")


class Lifecycle:
    """
    يربط عمر البرنامج بعمر النافذة.

    الواجهة ترسل نبضة كل بضع ثوانٍ، وتبعث ‎/bye عند إغلاقها. فإن أُغلقت
    النافذة انتهى البرنامج فوراً، وإن تعطّلت انتهى بعد المهلة. وبهذا لا
    يبقى خادم معلّقاً في الخلفية بلا نافذة تستعمله.

    المهلة طويلة عمداً: المتصفح يبطّئ مؤقتات الصفحات المصغَّرة إلى نبضة
    كل دقيقة، فمهلة قصيرة كانت ستُغلق البرنامج والمستخدم يعمل على غيره.
    """

    GRACE = 90.0            # مهلة الإقلاع حتى تفتح النافذة وتبدأ النبض
    TIMEOUT = 180.0         # أقصى صمت مقبول بعد أول نبضة
    FAREWELL_GRACE = 15.0   # مهلة بعد الوداع تكفي نبضةَ نافذةٍ أخرى
    CHECK_EVERY = 5.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._deadline = self.GRACE
        self._stop = threading.Event()

    def touch(self) -> None:
        """نبضة من نافذة حيّة — تُلغي أي وداع سابق."""
        with self._lock:
            self._last = time.monotonic()
            self._deadline = self.TIMEOUT

    def farewell(self) -> None:
        """
        نافذة أُغلقت.

        لا يُنهى البرنامج فوراً: قد تكون هناك نافذة أخرى مفتوحة على
        الوثيقة نفسها. فتُقصَّر المهلة إلى خمس عشرة ثانية، والنبضة
        تأتي كل عشر — فإن بقيت نافذة حيّة أعادت المهلة وأُلغي الإنهاء.
        """
        with self._lock:
            self._last = time.monotonic()
            self._deadline = self.FAREWELL_GRACE

    def expired(self) -> bool:
        with self._lock:
            return (time.monotonic() - self._last) > self._deadline

    def watch(self, on_expire) -> threading.Thread:
        def loop() -> None:
            while not self._stop.wait(self.CHECK_EVERY):
                if self.expired():
                    log.info("لا نافذة مفتوحة — يُغلق البرنامج")
                    on_expire()
                    return

        thread = threading.Thread(target=loop, name="masih-watchdog", daemon=True)
        thread.start()
        return thread

    def cancel(self) -> None:
        self._stop.set()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"Masih/{__version__}"

    # ---------------------------------------------------------------- أدوات
    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # الواجهة تُقدَّم من هنا، فلا داعي لفتح الخادم لمواقع أخرى.
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   MIME[".json"])

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"error": message})

    def _same_origin(self) -> bool:
        """
        يرفض الطلبات القادمة من صفحات خارجية.

        الطلب بلا Origin مقبول: هكذا تأتي طلبات سطر الأوامر وأدوات الفحص.
        أما المتصفح فيرسل Origin دائماً مع POST، فيُطابَق بأصلنا.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        allowed = {f"http://{HOST}:{port}", f"http://localhost:{port}"}
        return origin in allowed

    def _read_body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._error(400, "طول المحتوى غير صالح")
            return None
        if length <= 0:
            self._error(400, "الطلب فارغ")
            return None
        if length > limit:
            # الجسم يبقى غير مقروء، فيُقطع الاتصال بعد الردّ: لولا ذلك
            # لقُرئت بقيّته طلباً تالياً مشوّهاً.
            self.close_connection = True
            self._error(413, f"الملف أكبر من الحدّ المسموح ({limit // 1048576} ميجابايت)")
            return None
        return self.rfile.read(length)

    def _drain(self) -> None:
        """
        يبتلع جسم الطلب حين لا نحتاجه.

        الاتصال يبقى مفتوحاً لطلبات تالية (HTTP/1.1)، فبقاء بايتات جسمٍ
        غير مقروء في الأنبوب يجعل الطلب التالي يُقرأ من وسط الجسم.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if 0 < length <= MAX_SHEET:
            self.rfile.read(length)
        elif length != 0:
            # جسم ضخم أو ترويسة تالفة: يُقطع الاتصال بدل ابتلاع ميجابايتات
            # لا حاجة لها، أو ترك بقيّتها تُقرأ طلباً تالياً
            self.close_connection = True

    def _read_json(self, limit: int) -> dict | None:
        raw = self._read_body(limit)
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._error(400, "محتوى الطلب ليس JSON صالحاً")
            return None
        if not isinstance(data, dict):
            self._error(400, "محتوى الطلب يجب أن يكون كائن JSON")
            return None
        return data

    def _serve_asset(self, path: Path) -> None:
        """
        يقدّم مورداً مضمَّناً مع وسم يتغيّر بتغيّر الملف.

        no-cache لا تعني «لا تُخزِّن» بل «تحقّق قبل الاستعمال»: يردّ
        الخادم 304 إن لم يتغيّر الملف، فلا يُنقل شيء. والبديل — تخزين
        طويل بلا تحقّق — يجعل المتصفح يحتفظ بنسخة قديمة من الواجهة
        بعد تحديث البرنامج، فتظهر أعطال لا وجود لها في الشيفرة.
        """
        if not path.is_file():
            self._error(404, "المورد غير موجود")
            return
        try:
            info = path.stat()
        except OSError:
            self._error(404, "تعذّرت قراءة المورد")
            return
        etag = f'"{int(info.st_mtime)}-{info.st_size}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ctype = MIME.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), ctype,
                   {"Cache-Control": "no-cache", "ETag": etag})

    # ----------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0].rstrip("/") or "/"

        if route == "/health":
            self._json(200, {"ok": True, "app": "masih", "version": __version__})
            return
        # الإعدادات والجلسات تكشفان مسارات المستخدم ونصّ كتبه، فتمرّان
        # بحارس الأصل كما تمرّ الكتابة. والمتصفّح لا يُرسل Origin مع
        # التنقّل المباشر، وهو مسموح — أما صفحة أجنبية فترسله فتُردّ.
        if route in ("/settings", "/sessions") or route.startswith("/sessions/"):
            if not self._same_origin():
                self._drain()
                self._error(403, "طلب من أصل غير مسموح")
                return
            self._handle_read(route)
            return
        if route == "/quran.json":
            self._serve_asset(asset("quran.json"))
            return
        if route == "/favicon.svg":
            self._serve_asset(asset("favicon.svg"))
            return
        if route == "/quran-engine.js":
            self._serve_asset(asset("quran-engine.js"))
            return
        if route.startswith("/fonts/"):
            name = Path(route[len("/fonts/"):]).name  # يمنع الخروج من المجلد
            self._serve_asset(asset("fonts", name))
            return
        if route == "/":
            page = asset("index.html")
            if not page.is_file():
                self._send(500, "<meta charset=utf-8><h3>الواجهة مفقودة</h3>".encode(),
                           MIME[".html"])
                return
            self.lifecycle.touch()  # النافذة فُتحت
            self._send(200, page.read_bytes(), MIME[".html"],
                       {"Cache-Control": "no-store"})
            return

        self._error(404, "المسار غير معروف")

    do_HEAD = do_GET

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        if not self._same_origin():
            # يُبتلع الجسم قبل الردّ. والردُّ على طلبٍ بقي جسمه في
            # الأنبوب يُغلق الاتصال بإعادة تعيين، فتضيع رسالة الرفض
            # نفسها من الطرف الآخر ويرى «عطل شبكة» لا «أصل غير مسموح».
            self._drain()
            self._error(403, "طلب من أصل غير مسموح")
            return
        route = self.path.split("?", 1)[0].rstrip("/") or "/"

        # نبضات الحياة تُقرأ قبل أي شيء: هي أكثر الطلبات وأخفّها.
        if route == "/alive":
            self.lifecycle.touch()
            self._json(200, {"ok": True})
            return
        if route == "/bye":
            self.lifecycle.farewell()
            self._json(200, {"ok": True})
            return

        if route in ("/", "/pdf"):
            self._handle_pdf()
        elif route == "/ocr":
            self._handle_ocr()
        elif route == "/settings":
            self._handle_set_settings()
        elif route == "/pick-folder":
            self._handle_pick_folder()
        elif route == "/sessions":
            self._handle_save_session()
        elif route == "/reveal":
            self._handle_reveal()
        elif route == "/save-file":
            self._handle_save_file()
        elif route == "/open-file":
            self._handle_open_file()
        else:
            self._error(404, "المسار غير معروف")

    # -------------------------------------------------------------- DELETE
    def do_DELETE(self) -> None:  # noqa: N802
        self._drain()
        if not self._same_origin():
            self._error(403, "طلب من أصل غير مسموح")
            return
        route = self.path.split("?", 1)[0].rstrip("/") or "/"
        if not route.startswith("/sessions/"):
            self._error(404, "المسار غير معروف")
            return
        sid = unquote(route[len("/sessions/"):])
        path = forget_session(sid)
        if path is None:
            self._error(404, "لا توجد جلسة بهذا المعرّف")
            return
        log.info("حُذفت جلسة من السجل، وبقي ملفها: %s", path)
        self._json(200, {"ok": True, "file": path})

    @property
    def lifecycle(self) -> Lifecycle:
        return self.server.lifecycle  # type: ignore[attr-defined]

    # ------------------------------------------------- الإعدادات والجلسات
    def _handle_read(self, route: str) -> None:
        """قراءات الإعدادات والجلسات — كلّها بلا جسم طلب."""
        if route == "/settings":
            self._json(200, {"saveDir": str(save_dir()),
                             "defaultDir": str(default_save_dir())})
            return
        if route == "/sessions":
            self._json(200, {"sessions": list_sessions()})
            return
        sid = unquote(route[len("/sessions/"):])
        found = read_session(sid)
        if found is None:
            self._error(404, "لا توجد جلسة بهذا المعرّف")
            return
        self._json(200, found)

    def _handle_set_settings(self) -> None:
        data = self._read_json(MAX_JSON)
        if data is None:
            return
        path, why = check_dir(str(data.get("saveDir") or ""))
        if path is None:
            self._error(400, why)
            return
        settings = read_settings()
        settings["saveDir"] = str(path)
        try:
            write_settings(settings)
        except OSError as exc:
            log.warning("تعذّر حفظ الإعدادات: %s", exc)
            self._error(500, f"تعذّر حفظ الإعدادات: {exc.strerror or exc}")
            return
        log.info("مسار الحفظ صار %s", path)
        self._json(200, {"saveDir": str(path)})

    def _handle_pick_folder(self) -> None:
        """
        يفتح مختار المجلدات الأصيل.

        النداء يحجز خيطه حتى يُغلق المستخدم النافذة — وقد يطول. ولا خطر
        في ذلك: الخادم يخدم كل اتصال في خيط مستقل، فالنبض يواصل الوصول
        والبرنامج لا يُقتل وسط الاختيار. أما الخيط الرئيسي — حيث حلقة
        رسائل ويندوز — فلا ننتظره ونحن نمسك بقفل، فلا حلقة انتظار.
        والقفل هنا لغرض آخر: نافذتان للاختيار معاً تعلّقان الواجهة.
        """
        self._drain()
        from . import window as shell

        if not shell.native_alive():
            # وضع ‎--no-window أو صدَفة المتصفّح الاحتياطية: لا نافذة
            # أصيلة نطلب منها الحوار، فتعود الواجهة إلى حقل النصّ.
            self._error(501, "لا توجد نافذة أصيلة — اكتب المسار في الحقل")
            return
        if not _picker_lock.acquire(blocking=False):
            self._error(409, "نافذة اختيار المجلد مفتوحة أصلاً")
            return
        try:
            chosen = shell.pick_folder(str(save_dir()))
        except Exception as exc:  # noqa: BLE001 - أي عطب في الحوار الأصيل
            log.warning("تعذّر فتح مختار المجلدات: %s", exc)
            self._error(501, f"تعذّر فتح نافذة اختيار المجلد: {exc}")
            return
        finally:
            _picker_lock.release()
        if not chosen:
            self._json(200, {"cancelled": True})
            return
        self._json(200, {"path": chosen})

    def _handle_save_session(self) -> None:
        data = self._read_json(MAX_SHEET)
        if data is None:
            return
        markdown = data.get("markdown")
        if not isinstance(markdown, str):
            self._error(400, "نصّ الجلسة مفقود")
            return
        sid = data.get("id")
        if sid is not None and not isinstance(sid, str):
            self._error(400, "معرّف الجلسة غير صالح")
            return
        try:
            pages = int(data.get("pages") or 0)
        except (TypeError, ValueError):
            pages = 0
        try:
            saved = save_session(sid or None, str(data.get("title") or ""),
                                 markdown, pages)
        except KeyError:
            self._error(404, "لا توجد جلسة بهذا المعرّف")
            return
        except (OSError, ValueError) as exc:
            log.warning("تعذّر حفظ الجلسة: %s", exc)
            self._error(500, f"تعذّر حفظ ملف الجلسة: {exc}")
            return
        self._json(200, saved)

    def _handle_reveal(self) -> None:
        data = self._read_json(MAX_JSON)
        if data is None:
            return
        raw = str(data.get("path") or "").strip()
        if not raw:
            self._error(400, "لم يصل أي مسار")
            return
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.exists():
            self._error(404, "الملف لم يعد موجوداً في مكانه")
            return
        if sys.platform != "win32":
            self._error(501, "فتح المجلد متاح على ويندوز وحده")
            return
        try:
            if path.is_dir():
                os.startfile(str(path))  # noqa: S606
            else:
                # سطر أوامر واحد لا قائمة: مستكشف ويندوز يقرأ سطره بنفسه
                # ولا يفهم ‎/select, مفصولةً عن المسار بفراغ. ولا صدَفة
                # هنا (shell=False) فلا خطر في محارف المسار، والاقتباس
                # آمن لأن ويندوز يمنع علامة الاقتباس داخل أسماء الملفات.
                subprocess.Popen(f'explorer.exe /select,"{path}"',  # noqa: S603
                                 close_fds=True)
        except OSError as exc:
            log.warning("تعذّر فتح المجلد %s: %s", path, exc)
            self._error(500, f"تعذّر فتح المجلد: {exc.strerror or exc}")
            return
        self._json(200, {"ok": True})

    def _handle_save_file(self) -> None:
        """
        يكتب ملفاً مُصدَّراً في مجلد الحفظ — والبرنامج هو الذي يكتبه.

        وكان التصدير يمرّ بتنزيل المتصفّح: شريطٌ أسفل النافذة وسؤالٌ
        عن الإبقاء على الملف، فيخرج المستخدم من برنامجٍ إلى صفحة وِب.
        فصار الملفّ يصل إلى هنا بايتاتٍ مُرمَّزة، ويستقرّ في المجلد
        الذي اختاره في الإعدادات، ثم تُقال له كلمةٌ في الواجهة.

        والاسم لا يُصدَّق: يُنقّى بـ ‎safe_stem‎، ويُلحَق به امتدادٌ
        من قائمتنا لا من الطلب، ويُقارَن المسار بعد الحلّ بجذر المجلد
        قبل الكتابة (‎unique_export_path‎).
        """
        data = self._read_json(MAX_SAVE)
        if data is None:
            return
        kind = str(data.get("kind") or "").lower()
        suffix = SAVE_KINDS.get(kind)
        if suffix is None:
            self._error(400, "نوع الملف غير مدعوم")
            return
        raw_b64 = data.get("data")
        if not isinstance(raw_b64, str) or not raw_b64:
            self._error(400, "لم تصل بيانات الملف")
            return
        try:
            blob = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            self._error(400, "بيانات الملف ليست ترميزاً صالحاً")
            return
        if not blob:
            self._error(400, "الملف فارغ")
            return

        # الامتداد يُنزع من الاسم الوارد ثم يُعاد من عندنا: لئلّا
        # يخرج «كتاب.pdf» ملفاً اسمه «كتاب.pdf.pdf»، ولا يُمرَّر
        # امتدادٌ ثانٍ مدسوسٌ في الاسم.
        stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", str(data.get("name") or ""))
        folder = save_dir()
        try:
            target = unique_export_path(folder, stem, suffix)
            atomic_write_bytes(target, blob)
        except ValueError as exc:
            log.warning("اسم ملف مرفوض عند التصدير: %s", exc)
            self._error(400, str(exc))
            return
        except OSError as exc:
            log.warning("تعذّرت كتابة الملف المُصدَّر في %s: %s", folder, exc)
            self._error(500, f"تعذّر حفظ الملف: {exc.strerror or exc}")
            return
        log.info("حُفظ ملف مُصدَّر (%s) في %s بحجم %.0f ك.ب",
                 kind, target, len(blob) / 1024)
        self._json(200, {"ok": True, "file": str(target), "name": target.name})

    def _handle_open_file(self) -> None:
        """
        يفتح ملفاً كتبناه نحن بالبرنامج المقترن به في النظام.

        و‎/reveal‎ يكشف الملفَّ في مجلده، وهذا يفتحه نفسه — وهو
        الفعل الذي يريده من صدَّر كتاباً للتوّ. والفرق بينهما في
        الخطر: الفتح تشغيل، فلا يُقبل إلا مسارٌ ثبت أنه ملفٌّ داخل
        مجلد الحفظ (‎inside_save_dir‎)، وما عداه يُردّ ٤٠٣.
        """
        data = self._read_json(MAX_JSON)
        if data is None:
            return
        path = inside_save_dir(str(data.get("path") or ""))
        if path is None:
            self._error(403, "لا يُفتح إلا ملفٌّ داخل مجلد الحفظ")
            return
        if sys.platform != "win32":
            self._error(501, "فتح الملف متاح على ويندوز وحده")
            return
        try:
            os.startfile(str(path))  # noqa: S606
        except OSError as exc:
            log.warning("تعذّر فتح الملف %s: %s", path, exc)
            self._error(500, f"تعذّر فتح الملف: {exc.strerror or exc}")
            return
        log.info("فُتح ملف مُصدَّر: %s", path)
        self._json(200, {"ok": True})

    def _handle_pdf(self) -> None:
        raw = self._read_body(MAX_SHEET)
        if raw is None:
            return
        html = raw.decode("utf-8", "replace")
        try:
            pdf = build_pdf(html)
        except MissingDependency as exc:
            log.error("بناء PDF فشل: %s", exc)
            self._error(503, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - أي عطب يُبلَّغ للواجهة
            log.exception("بناء PDF فشل")
            self._error(500, f"تعذّر بناء الملف: {exc}")
            return
        note = selectable_report(pdf)
        log.info("بُني PDF بحجم %.0f ك.ب%s", len(pdf) / 1024,
                 f" · {note}" if note else "")
        self._send(200, pdf, "application/pdf",
                   {"Content-Disposition": 'attachment; filename="masih.pdf"'})

    def _handle_ocr(self) -> None:
        """
        يمرّر طلب المسح الضوئي إلى Mistral.

        المتصفح يمنع الاتصال المباشر بـ api.mistral.ai من صفحة محلية،
        فيمرّ الطلب من هنا. المفتاح يُنقل كما هو ولا يُسجَّل ولا يُخزَّن.
        """
        key = self.headers.get("X-Api-Key", "").strip()
        if not key:
            self._error(401, "لم يصل مفتاح الـ API")
            return
        raw = self._read_body(MAX_UPLOAD)
        if raw is None:
            return

        request = urllib.request.Request(
            MISTRAL_OCR_URL, data=raw, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=OCR_TIMEOUT) as reply:
                body = reply.read()
            log.info("تمّ المسح الضوئي (%.0f ك.ب مُرسَلة)", len(raw) / 1024)
            self._send(200, body, MIME[".json"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            # يُضاف تلخيصٌ للتفصيل في السجل — إن قال Mistral «Check your
            # subscription» أو «insufficient credits» عرفنا عين ما شكاه
            # ولم يظنّ المستخدم أن العطب في البرنامج.
            snippet = re.sub(r"\s+", " ", detail)[:180]
            log.warning("ردّ Mistral برمز %s — %s", exc.code, snippet)
            self._send(exc.code, detail.encode("utf-8"), MIME[".json"])
        except urllib.error.URLError as exc:
            log.warning("تعذّر الوصول إلى Mistral: %s", exc.reason)
            self._error(502, f"تعذّر الوصول إلى خادم المسح الضوئي: {exc.reason}")
        except TimeoutError:
            self._error(504, "انتهت مهلة المسح الضوئي")

    # يُكتم سجل الخادم الافتراضي؛ التسجيل يمرّ عبر logging وحده.
    def log_message(self, *args) -> None:  # noqa: A003
        pass


# ============================================================ إدارة المنفذ
def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((HOST, port)) == 0


def masih_already_running(port: int) -> bool:
    """يميّز نسخة أخرى من ماسح عن برنامج آخر يحتلّ المنفذ نفسه."""
    try:
        with urllib.request.urlopen(
                f"http://{HOST}:{port}/health", timeout=1.5) as reply:
            return json.loads(reply.read()).get("app") == "masih"
    except Exception:  # noqa: BLE001
        return False


def create(port: int = DEFAULT_PORT,
           lifecycle: Lifecycle | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.daemon_threads = True
    server.lifecycle = lifecycle or Lifecycle()  # type: ignore[attr-defined]
    return server


def free_port(preferred: int = DEFAULT_PORT, tries: int = 12) -> int | None:
    """
    يُرجع أول منفذ متاح ابتداءً من المفضَّل، أو None إن كان ماسح يعمل أصلاً.

    المنفذ المفضَّل يُحاوَل أولاً دائماً حفاظاً على مخزن المتصفح.
    """
    for offset in range(tries):
        port = preferred + offset
        if not port_in_use(port):
            return port
        if offset == 0 and masih_already_running(port):
            return None
    raise OSError(f"لا يوجد منفذ متاح بين {preferred} و{preferred + tries - 1}")
