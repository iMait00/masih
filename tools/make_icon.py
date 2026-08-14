"""
يولّد أيقونة البرنامج masih.ico وأيقونة الصفحة favicon.svg من مخطوطة «ماسح».

تُبنى الأيقونة برمجياً لا تُنسخ جاهزة: فلا يحتاج البناء إلى إنترنت
ولا إلى أداة رسم، وتبقى النتيجة واحدة على أي جهاز.

المصدر هنا هو مسارات المخطوطة نفسها (WORDMARK/NOTCH أدناه) لا حرفٌ من خط،
ويُرسَم المسار بمُسطِّح ذاتي صغير: نقسّم منحنيات بيزيه إلى مضلّعات ثم نملؤها
بقاعدة اللَفّ اللاصفري (nonzero) على لوحة مُكبَّرة، ثم نُصغّرها. لا مكتبة
إضافية: Pillow وحدها، وهي أصلاً في البناء.

    python tools/make_icon.py                 # يكتب masih.ico و favicon.svg
    python tools/make_icon.py --preview DIR   # يكتب معها معاينات PNG لكل مقاس
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "masih" / "assets"
OUT_ICO = ASSETS / "masih.ico"
OUT_SVG = ASSETS / "favicon.svg"

# ---------------------------------------------------------------- المخطوطة --
# مأخوذة كما هي من شعار «ماسح» ‎viewBox="0 0 404.43 294.1"‎.
VIEWBOX = (0.0, 0.0, 404.43, 294.1)

WORDMARK = [
    "M128.18,121.96l-11.45,26.02-28.07,6.92c-4.66,37.28,48.32,37.07,65.93,14.92,"
    "4.42-5.56,7.08-15.45,15.58-15.89-.19,7.65-6.34,15.73-2.76,23.24,4.02,8.45,"
    "15.84,8.26,23.1,4.55,12.7-6.48,9.37-29.28,23.66-33.79-2.07,13.83-7.6,19.27,"
    "4.99,29.47,2.83,2.3,20.8,12.66,23.01,10.47.03-3.26-.99-6.45-1.96-9.52-2.01"
    "-6.36-11.51-22.66-11.74-27.09-.29-5.59,10.09-19.45,12.21-25.31,3.01,1.47,"
    "13.43,29.04,14.24,33.71,2.7,15.39-3.94,34.31-11.93,47.49-5.71,9.42-6.36,"
    "10.46-17.81,7.19-9.97-2.84-17.43-10.44-23.5-18.46-10.16,20.31-42.37,30.08"
    "-47.51.98-9.24,8.9-18.2,16.44-31.61,17.85-40.04,4.21-49.28-25.17-41.39"
    "-58.81-25.14,7.28-64,25.81-66.98,55.44-5.23,51.94,65.63,55.08,101.37,51.31,"
    "8.17-.86,18.93-4.34,26.4-4.63,1.65-.06,2.05-.44,3.21,1.25-.03.99-12.57,"
    "10.88-14.52,12.44-14.18,11.34-23.01,20.7-41.97,22.01-33.22,2.28-75.59-5.78"
    "-85.19-42.74-8.26-31.8,5.54-70.02,29.69-91.61,9.33-8.34,20.91-13.55,31.01"
    "-20.45-14.08-4.48-27.18-9.7-42.39-7.89-8.45,1-17.4,7.32-17.61,16.29-6.91,"
    "2.51-3.36-10.45-2.51-14.41,13.7-63.81,71.12-10.98,105.01-10.98h21.5Z",

    "M241.23.14c2.13-1.46,11.67,8.82,13.46,10.93,41.09,48.25,28.48,113.28,34.5,"
    "170.3,1.93,18.26,4.9,32.02,27.25,28.24,29.24-4.95,27.71-61.4,59.77-53.23,"
    "13.28,3.39,26.42,26.22,27.87,39.09,2.03,18.12-4.96,32.45-14.9,46.89-18.77"
    "-4.3-39.72-10.39-52.49-25.51-7.22,13.46-18.26,24.86-34.85,23.86-21.49-1.3"
    "-25.71-21.86-27.64-39.37-2.65-24.04-.83-49.66-3.02-73.89-3.3-36.5-14.29"
    "-74.55-41.83-100.03L241.23.14ZM390.18,211.84c-3.1-12.36-22.59-35.44-36.34"
    "-25.81-7.54,5.28-1.28,9.23,4.03,12.65,3.37,2.18,30.88,14.53,32.32,13.16Z",

    "M309.19,137.93l4.68-11.05,90.31-33.89c.41.51-3.16,10.79-5.24,11.23l-89.74,"
    "33.71Z",

    "M234.92,242.56l-63.74,24.22c1.9-3.3,1.51-8.19,5.27-10.2l61.23-23.74-2.76,"
    "9.73Z",
]

# فراغٌ داخل الشعار (‎class="notch"‎ في الصفحة): يُقتطع من الحبر ولا يُلوَّن به.
NOTCH = (
    "M390.18,211.84c-1.44,1.37-28.94-10.98-32.32-13.16-5.31-3.42-11.57-7.37"
    "-4.03-12.65,13.75-9.63,33.24,13.45,36.34,25.81Z"
)

# ------------------------------------------------------------------ الألوان --
# لوحة البرنامج الجديدة: أزرق عميق أرضيةً، والمخطوطة بلون كريمي.
ABYSS = "#05102D"   # أزرق سحيق — الأرضية
CREAM = "#FFF7E3"   # أبيض كريمي — الحبر
GOLD = "#B89343"    # ذهب — حاشية رفيعة تفصل الأيقونة عن الخلفيات الداكنة

GROUND = ABYSS
INK = CREAM
RIM = GOLD

SIZES = [16, 24, 32, 48, 64, 128, 256]

RES = 2048          # دقّة اللوحة المُكبَّرة التي يُرسم عليها الحبر
CORNER = 0.22       # نصف قطر زوايا المربّع، نسبةً إلى ضلعه
RIM_W = 0.022       # سمك الحاشية الذهبية، نسبةً إلى الضلع

# ============================================================================
# الكلمة كاملةً في كلّ مقاس، بلا حاشية ولا اقتطاع.
#
# كان في الأمر خطآن قبل هذا:
#
# الأول أنّ المقاسات الصغيرة كانت تقتطع «ما» من صدر المخطوطة وحدها،
# فتُرى الأيقونة في شريط النافذة مبتورةً لا تُشبه التي على سطح المكتب.
#
# والثاني — وهو علّة الأول — أنّ المخطوطة كانت تُقاس إلى الضلع الأطول
# من المربّع. وهي عريضةٌ قصيرة (‎٤٠٤×٢٩٤‎، نسبتها ١٫٣٨)، فإذا وُسِّطت في
# مربّعٍ ذهب نحو ثُلث عرضه هواءً فوقها وتحتها، وضاق ما بقي للحروف حتى
# تتلبّد. فبدا أن لا مخرج إلا الاقتطاع.
#
# فتُقاس الآن إلى العرض لا إلى الضلع الأطول: تملأ المخطوطة عرض المربّع
# وتتوسّطه ارتفاعاً، فتكسب من البكسلات نحو الثلث. وبذلك تُقرأ الكلمة
# كاملةً حتى ستّة عشر بكسلاً بلا قصّ.
#
# ولا حاشية ذهبية: كانت خيطاً محيطاً بالأيقونة، وهو من الـstroke الذي
# لا يريده. فالأرضيةُ الداكنة وحدها هي الصدَفة.
# ============================================================================
LAYOUTS = {
    "hero": dict(view=VIEWBOX, margin=0.060, weight=0.000, rim=False),
    "mid":  dict(view=VIEWBOX, margin=0.040, weight=0.006, rim=False),
    "fine": dict(view=VIEWBOX, margin=0.020, weight=0.010, rim=False),
}
LAYOUT_FOR = {16: "fine", 24: "fine", 32: "mid", 48: "mid"}
DEFAULT_LAYOUT = "hero"


def layout_for(size: int) -> str:
    return LAYOUT_FOR.get(size, DEFAULT_LAYOUT)


# =========================================================== مسارات SVG =====

_TOKEN = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?|[A-Za-z]")
_SUPPORTED = set("MmLlHhVvCcSsZz")


def _tokens(d: str) -> list[str]:
    """يفصل نصّ المسار إلى أوامر وأرقام، ويعترض على أيّ أمر غير مدعوم."""
    out = _TOKEN.findall(d)
    seen = {t for t in out if t.isalpha()}
    unknown = seen - _SUPPORTED
    if unknown:
        raise ValueError(f"أمر مسار غير مدعوم: {sorted(unknown)}")
    # طول النصّ المُلتقَط يجب أن يساوي طول الأصل بعد حذف الفواصل والمسافات
    stripped = re.sub(r"[\s,]", "", d)
    if len("".join(out)) != len(stripped):
        raise ValueError("تعذّر تحليل نصّ المسار كاملاً")
    return out


def _cubic(p0, p1, p2, p3, steps: int) -> list[tuple[float, float]]:
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        a, b, c, e = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
    return pts


def _steps(p0, p1, p2, p3, scale: float) -> int:
    span = (math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)) * scale
    return max(8, min(128, int(span / 3.0) + 1))


def flatten(d: str, scale: float = 1.0) -> list[list[tuple[float, float]]]:
    """يحوّل مسار SVG إلى قائمة كنتورات (مضلّعات) بإحداثيات المستخدم.

    `scale` هو معامل التكبير الذي سيُرسم به لاحقاً، ويُستعمل فقط لاختيار
    عدد تقسيمات المنحنى حتى يبقى الخطأ دون البكسل.
    """
    toks = _tokens(d)
    i = 0
    cmd = ""
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_c2: tuple[float, float] | None = None
    contours: list[list[tuple[float, float]]] = []
    contour: list[tuple[float, float]] = []

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if len(contour) > 2:
                    contours.append(contour)
                contour = []
                cur = start
                prev_c2 = None
                continue
        low = cmd.lower()
        rel = cmd.islower()

        if low == "m":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            if len(contour) > 2:
                contours.append(contour)
            cur = start = (x, y)
            contour = [cur]
            prev_c2 = None
            cmd = "l" if rel else "L"          # ما بعد m ضمنيّاً خطوط
            continue

        if low == "l":
            x, y = num(), num()
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            contour.append(cur)
            prev_c2 = None
            continue

        if low == "h":
            x = num()
            cur = (cur[0] + x if rel else x, cur[1])
            contour.append(cur)
            prev_c2 = None
            continue

        if low == "v":
            y = num()
            cur = (cur[0], cur[1] + y if rel else y)
            contour.append(cur)
            prev_c2 = None
            continue

        if low in ("c", "s"):
            if low == "c":
                c1 = (num(), num())
                c2 = (num(), num())
                end = (num(), num())
                if rel:
                    c1 = (cur[0] + c1[0], cur[1] + c1[1])
                    c2 = (cur[0] + c2[0], cur[1] + c2[1])
                    end = (cur[0] + end[0], cur[1] + end[1])
            else:
                c2 = (num(), num())
                end = (num(), num())
                if rel:
                    c2 = (cur[0] + c2[0], cur[1] + c2[1])
                    end = (cur[0] + end[0], cur[1] + end[1])
                c1 = (cur if prev_c2 is None
                      else (2 * cur[0] - prev_c2[0], 2 * cur[1] - prev_c2[1]))
            contour.extend(_cubic(cur, c1, c2, end, _steps(cur, c1, c2, end, scale)))
            cur, prev_c2 = end, c2
            continue

        raise ValueError(f"أمر غير متوقّع: {cmd!r}")

    if len(contour) > 2:
        contours.append(contour)
    return contours


# ============================================================== التنقيط =====

def rasterize(contours, width: int, height: int) -> Image.Image:
    """يملأ الكنتورات بقاعدة اللَفّ اللاصفري ويُعيد قناعاً ثنائيّ الحدّ."""
    edges = []
    for pts in contours:
        n = len(pts)
        for k in range(n):
            (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
            if y0 == y1:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), 1))
            else:
                edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1), -1))

    buckets: dict[int, list] = {}
    for e in edges:
        row = min(max(int(e[0]), 0), height - 1)
        buckets.setdefault(row, []).append(e)

    mask = bytearray(width * height)
    active: list = []
    fill = b"\xff"
    for y in range(height):
        if y in buckets:
            active.extend(buckets[y])
        yc = y + 0.5
        if active:
            active = [e for e in active if e[1] > yc]
        if not active:
            continue
        xs = [(x0 + (yc - y0) * slope, w)
              for (y0, y1, x0, slope, w) in active if y0 <= yc < y1]
        if not xs:
            continue
        xs.sort()
        wind = 0
        span_start = 0.0
        base = y * width
        for x, w in xs:
            was = wind
            wind += w
            if was == 0 and wind != 0:
                span_start = x
            elif was != 0 and wind == 0:
                a = min(max(int(math.ceil(span_start - 0.5)), 0), width)
                b = min(max(int(math.ceil(x - 0.5)), 0), width)
                if b > a:
                    mask[base + a:base + b] = fill * (b - a)
    return Image.frombytes("L", (width, height), bytes(mask))


# ============================================================== التركيب =====

def _bbox(contours) -> tuple[float, float, float, float]:
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    return min(xs), min(ys), max(xs), max(ys)


def _placement(view, margin: float, res: int):
    """يُعيد معاملات التحويل من إحداثيات المخطوطة إلى لوحة مربّعة ضلعها res.

    القياس إلى العرض لا إلى الضلع الأطول: المخطوطة عريضةٌ قصيرة، فلو
    قِيست إلى الأطول لضاقت وتُرك فوقها وتحتها هواءٌ لا ينتفع به. فتملأ
    العرضَ وتتوسّط الارتفاع، وهو ما يُبقيها مقروءةً في أصغر المقاسات.
    """
    vx, vy, vw, vh = view
    scale = (1.0 - 2 * margin) * res / vw
    ox = (res - vw * scale) / 2.0 - vx * scale
    oy = (res - vh * scale) / 2.0 - vy * scale
    return scale, ox, oy


def ink_mask(layout: str, res: int = RES) -> Image.Image:
    """قناع الحبر: المخطوطة مملوءة، والفراغ الداخلي مقتطعٌ منها."""
    spec = LAYOUTS[layout]
    weight = spec["weight"]
    scale, ox, oy = _placement(spec["view"], spec["margin"], res)

    def place(d):
        return [[(x * scale + ox, y * scale + oy) for (x, y) in c]
                for c in flatten(d, scale)]

    strokes = [c for d in WORDMARK for c in place(d)]
    mask = rasterize(strokes, res, res)

    if weight > 0:                      # تغليظ للمقاسات الصغيرة
        width = max(1, int(round(weight * res)))
        draw = ImageDraw.Draw(mask)
        for c in strokes:
            draw.line(list(c) + [c[0]], fill=255, width=width, joint="curve")

    # الفراغ الداخلي: كنتوره داخل المسار الثاني معاكس الاتّجاه، فقاعدة اللَفّ
    # اللاصفري تُخرجه ثقباً من تلقاء نفسها. والصفحة تطليه فوق ذلك بلون اللوحة
    # صراحةً (‎class="notch"‎)، فنقتطعه هنا صراحةً كذلك: احتياطٌ يضمن النتيجة
    # نفسها لو انقلب اتّجاه الكنتور يوماً أو غلُظ الخطّ حتى ردمه.
    notch = rasterize(place(NOTCH), res, res)
    mask.paste(0, (0, 0), notch)
    return mask


def _ground(size: int, rim: bool) -> Image.Image:
    """المربّع المُدوَّر بلون الأرضية، وحاشية ذهبية رفيعة عند الحاجة."""
    ss = 8
    box = size * ss
    img = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, box - 1, box - 1],
                           radius=int(box * CORNER), fill=GROUND)
    if rim:
        # الحدّ الأدنى بكسلٌ كامل بعد التصغير (‎ss‎ من وحدات اللوحة المُكبَّرة):
        # دونه تذوب الحاشية في المقاسات الصغيرة فتعود الأيقونة بلا إطار.
        w = max(ss, int(round(RIM_W * box)))
        draw.rounded_rectangle([w / 2, w / 2, box - 1 - w / 2, box - 1 - w / 2],
                               radius=int(box * CORNER - w / 2),
                               outline=RIM, width=w)
    return img.resize((size, size), Image.LANCZOS)


def frames() -> list[Image.Image]:
    masks = {name: ink_mask(name) for name in LAYOUTS}
    out = []
    for size in SIZES:
        name = layout_for(size)
        tile = _ground(size, LAYOUTS[name]["rim"])
        alpha = masks[name].resize((size, size), Image.LANCZOS)
        tile.paste(Image.new("RGBA", (size, size), INK), (0, 0), alpha)
        out.append(tile)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="يولّد masih.ico و favicon.svg")
    ap.add_argument("--preview", metavar="DIR",
                    help="مجلّد تُكتب فيه معاينات PNG لكل مقاس")
    args = ap.parse_args()

    tiles = frames()
    tiles[-1].save(OUT_ICO, format="ICO",
                   sizes=[(s, s) for s in SIZES], append_images=tiles[:-1])
    OUT_SVG.write_text(svg_markup(), encoding="utf-8")

    if args.preview:
        folder = Path(args.preview)
        folder.mkdir(parents=True, exist_ok=True)
        with Image.open(OUT_ICO) as ico:
            for size in SIZES:
                ico.size = (size, size)
                ico.load()
                ico.convert("RGBA").save(folder / f"masih-{size:03d}.png")
                zoom = 8 if size <= 32 else 1
                if zoom > 1:
                    ico.convert("RGBA").resize(
                        (size * zoom, size * zoom), Image.NEAREST
                    ).save(folder / f"masih-{size:03d}@{zoom}x.png")
        print(f"معاينات في {folder}")

    print(f"كُتبت {OUT_ICO.name} — {OUT_ICO.stat().st_size} بايت، مقاسات {SIZES}")
    print(f"كُتبت {OUT_SVG.name} — {OUT_SVG.stat().st_size} بايت")


def svg_markup() -> str:
    """أيقونة الصفحة: المخطوطة نفسها والألوان نفسها، بتخطيط الأيقونة الكبيرة.

    ولا حاشيةَ فيها كما لا حاشية في الأيقونة: الأرضية الداكنة وحدها.
    """
    side = 512
    scale, ox, oy = _placement(VIEWBOX, LAYOUTS["hero"]["margin"], side)
    tx = f"translate({ox:.3f} {oy:.3f}) scale({scale:.6f})"
    paths = "\n".join(f'<path d="{d}"/>' for d in WORDMARK)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}">
<rect x="0" y="0" width="{side}" height="{side}" rx="{side * CORNER:.0f}" fill="{GROUND}"/>
<g transform="{tx}">
<g fill="{INK}">
{paths}
</g>
<path fill="{GROUND}" d="{NOTCH}"/>
</g>
</svg>
"""


if __name__ == "__main__":
    main()
