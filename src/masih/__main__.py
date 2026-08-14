"""
نقطة الدخول.

نقرة مزدوجة على masih.exe تكفي: يقلع الخادم في الخلفية، وتُفتح نافذة
التطبيق، ولا تظهر نافذة أوامر. وحين تُغلق النافذة ينتهي البرنامج.

للمطوّرين:
    python -m masih                      كما يعمل عند المستخدم
    python -m masih --console            مع سجل مرئي في الطرفية
    python -m masih --check              فحص ذاتي ثم خروج
    python -m masih --file ورقة.html     بناء PDF بلا خادم ولا نافذة
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from . import __version__, app_dir
from .pdfbuild import (HB_VERSION, MissingDependency, build_pdf,
                       require_dependencies, selectable_report, self_test)
from .server import HOST, DEFAULT_PORT, Lifecycle, create, free_port
from .window import alert, close_window, native_alive, open_window

log = logging.getLogger("masih")


def say(message: str = "", error: bool = False) -> None:
    """طباعة لا تنكسر حين لا تكون هناك طرفية (بناء بلا نافذة أوامر)."""
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        log.info(message) if not error else log.error(message)
        return
    print(message, file=stream)


# ============================================================ السجل
def log_file() -> Path:
    """
    ملف السجل في مجلد بيانات المستخدم لا بجانب البرنامج.

    الـ exe قد يجلس في مجلد لا يملك المستخدم حقّ الكتابة فيه، فالكتابة
    بجانبه تفشل صامتة ونفقد أثر أي عطل.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME")
    folder = Path(base) / "Masih" if base else app_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "masih.log"
    except OSError:
        return app_dir() / "masih.log"


def attach_console() -> bool:
    """
    يربط البرنامج بنافذة الأوامر التي شغّلته، إن وُجدت.

    الـ exe مبنيّ بلا نافذة أوامر (وهو المطلوب عند النقر المزدوج)، وثمن
    ذلك أن sys.stdout يصير None فتضيع مخرجات ‎--check و‎--file صامتة.
    فإن شُغّل من طرفية نستعير نافذتها، وإلا بقي صامتاً كما ينبغي.
    """
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return sys.stdout is not None
    try:
        import ctypes

        ATTACH_PARENT = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT):
            return False
        # بدون ترميز UTF-8 تخرج الرسائل العربية رموزاً في نافذة الأوامر
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        return True
    except Exception:  # noqa: BLE001
        return False


LOG_MAX_BYTES = 512 * 1024


def setup_logging(console: bool) -> None:
    handlers: list[logging.Handler] = []
    path = log_file()
    try:
        # الإضافة لا الكتابة من جديد: قد تعمل نسختان معاً، والكتابة
        # من جديد تمحو سجلّ الأخرى فيضيع أثر أي عطل.
        if path.is_file() and path.stat().st_size > LOG_MAX_BYTES:
            path.unlink()
        handlers.append(logging.FileHandler(path, mode="a", encoding="utf-8"))
    except OSError:
        pass
    # sys.stdout يكون None في البناء بلا نافذة أوامر
    if console and sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO, handlers=handlers, force=True,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S")
    # fontTools يطبع سطراً لكل جدول في الخط عند تجزئته، فيغرق السجل
    # بمئات الأسطر التي لا تعني المستخدم ولا تفيد في تشخيص عطل.
    for noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib",
                  "fpdf", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ============================================================ الأوضاع
def run_app(console: bool, open_ui: bool = True) -> int:
    """الوضع المعتاد: خادم محلي + نافذة تطبيق."""
    try:
        require_dependencies()
    except MissingDependency as exc:
        log.error("%s", exc)
        alert("ماسح", str(exc))
        return 1

    check = self_test()
    # رقم العملية يميّز السطور حين تكتب نسختان في السجل نفسه
    log.info("——— ماسح %s · عملية %s · التشكيل uharfbuzz %s · الفحص الذاتي: %s",
             __version__, os.getpid(), HB_VERSION, check)
    if not check.startswith("سليم"):
        alert("ماسح",
              f"فحص التشكيل العربي لم ينجح: {check}\n\n"
              "قد تخرج ملفات الـ PDF بنص مقلوب.")

    try:
        port = free_port(DEFAULT_PORT)
    except OSError as exc:
        log.error("%s", exc)
        alert("ماسح", str(exc))
        return 1

    if port is None:
        # نسخة أخرى تعمل: تُفتح نافذة عليها بدل تشغيل خادم ثانٍ
        log.info("ماسح يعمل أصلاً على المنفذ %s — تُفتح نافذة عليه", DEFAULT_PORT)
        if open_ui:
            open_window(f"http://{HOST}:{DEFAULT_PORT}/")
        return 0

    if port != DEFAULT_PORT:
        log.warning("المنفذ %s مشغول ببرنامج آخر — استُعمل %s. "
                    "الوثائق المحفوظة سابقاً مربوطة بالمنفذ الأول.",
                    DEFAULT_PORT, port)

    lifecycle = Lifecycle()
    server = create(port, lifecycle)
    url = f"http://{HOST}:{port}/"

    def shutdown() -> None:
        # النافذة تُغلق أولاً: نافذة حيّة على خادم ميت تعرض عطلاً لا يفهمه
        # أحد. وحين يأتي النداء من إغلاق النافذة نفسها كان هذا لا يفعل شيئاً.
        close_window()
        threading.Thread(target=server.shutdown, daemon=True).start()

    def on_silence() -> None:
        """
        انقطع النبض. هل يُنهى البرنامج؟

        النبض احتياطٌ للحالة التي لا يصلنا فيها خبر الإغلاق: نافذة
        متصفّح في عملية أخرى. أما النافذة الأصيلة فإغلاقها يصلنا حدثاً،
        ووجودها وحده شهادةُ حياة. ومحرّك العرض يبطّئ مؤقتات الصفحة
        المصغَّرة حتى تكاد تقف، فإنهاء البرنامج لانقطاع نبضها يقتل عمل
        مستخدم لم يفعل شيئاً سوى أنه صغّر النافذة.
        """
        if native_alive():
            lifecycle.touch()
            lifecycle.watch(on_silence)   # الحارس ينتهي بعد أول إنذار
            log.info("انقطع النبض والنافذة مفتوحة — يُتجاهل")
            return
        shutdown()

    lifecycle.watch(on_silence)

    # الخادم في خيط جانبي: النافذة الأصيلة تحتاج الخيط الرئيسي لنفسها،
    # فحلقة رسائل ويندوز لا تعمل في غيره.
    serving = threading.Thread(target=server.serve_forever,
                               name="masih-http", daemon=True)
    serving.start()
    log.info("الخادم يعمل على %s", url)

    if console:
        say(f"\n  ماسح {__version__}")
        say(f"  العنوان: {url}")
        say("  أغلق النافذة لإنهاء البرنامج، أو اضغط Ctrl+C\n")

    try:
        if not open_ui:
            log.info("بلا نافذة — الخادم وحده يعمل")
            wait_for(serving)
        elif not open_window(url, on_close=shutdown):
            # الواجهة في متصفّح بعملية أخرى: لا حدث إغلاق يصلنا، فالعمر
            # معلّق بالنبض وحده كما كان قبل النافذة الأصيلة.
            wait_for(serving)
    except KeyboardInterrupt:
        log.info("أُوقف بطلب المستخدم")
    finally:
        lifecycle.cancel()
        server.shutdown()
        serving.join(timeout=5)
        server.server_close()
    log.info("انتهى")
    return 0


def wait_for(thread: threading.Thread) -> None:
    """
    انتظار خيط الخادم بلا ابتلاع Ctrl+C.

    join بلا مهلة على ويندوز ينام في نداء لا يقاطعه المستخدم، فتبقى
    الطرفية معلّقة. الانتظار على دفعات يعيد الخيط الرئيسي إلى بايثون
    بين الحين والآخر فتصل المقاطعة.
    """
    while thread.is_alive():
        thread.join(0.5)


def run_batch(target: str) -> int:
    """يحوّل ورقة HTML مُصدَّرة (أو مجلداً منها) إلى PDF بلا واجهة."""
    path = Path(target).expanduser()
    if not path.exists():
        print(f"غير موجود: {path}", file=sys.stderr)
        return 1
    files = sorted(path.glob("*.html")) if path.is_dir() else [path]
    if not files:
        say(f"لا توجد ملفات html في {path}", error=True)
        return 1

    failures = 0
    for index, source in enumerate(files, 1):
        say(f"[{index}/{len(files)}] {source.name}")
        try:
            pdf = build_pdf(source.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            say(f"    فشل: {exc}", error=True)
            failures += 1
            continue
        out = source.with_suffix(".pdf")
        out.write_bytes(pdf)
        note = selectable_report(pdf)
        say(f"    {out.name} ({len(pdf) / 1024:.0f} ك.ب)"
            + (f" · {note}" if note else ""))
    return 1 if failures else 0


def run_check() -> int:
    from .fonts import describe

    result = self_test()
    say(f"ماسح {__version__}")
    say(f"  التشكيل  : uharfbuzz {HB_VERSION or 'مفقود'}")
    say(f"  الخطوط   : {describe()}")
    say(f"  الفحص    : {result}")
    say(f"  السجل    : {log_file()}")
    return 0 if result.startswith("سليم") else 1


# ============================================================ التشغيل
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="masih", description="ماسح — وثائق عربية سليمة قابلة للنسخ")
    parser.add_argument("--console", action="store_true",
                        help="إظهار السجل في الطرفية")
    parser.add_argument("--check", action="store_true",
                        help="فحص ذاتي ثم خروج")
    parser.add_argument("--file", metavar="مسار",
                        help="بناء PDF من ورقة html أو مجلد، بلا واجهة")
    parser.add_argument("--no-window", action="store_true",
                        help="تشغيل الخادم بلا فتح نافذة (للفحص الآلي)")
    parser.add_argument("--version", action="version", version=f"masih {__version__}")
    args = parser.parse_args(argv)

    # عند الضغط المزدوج لا توجد طرفية، فالسجل إلى الملف وحده. أما إن
    # شُغّل من طرفية بأحد الخيارات فنستعير نافذتها لتظهر المخرجات.
    wants_console = args.console or args.check or bool(args.file)
    console = attach_console() if wants_console else (
        not _frozen() and sys.stdout is not None)
    setup_logging(console)

    try:
        if args.check:
            return run_check()
        if args.file:
            return run_batch(args.file)
        return run_app(console, open_ui=not args.no_window)
    except Exception as exc:  # noqa: BLE001
        log.exception("عطل غير متوقّع")
        alert("ماسح", f"عطل غير متوقّع:\n\n{exc}\n\nالتفاصيل في:\n{log_file()}")
        return 1


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


if __name__ == "__main__":
    raise SystemExit(main())
