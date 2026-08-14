"""
اختبارات مولّد الأيقونة: تحليل مسارات المخطوطة، وتنقيطها، وسلامة masih.ico.

تشغيل:  python -m unittest discover -s tests -v
تستعمل unittest المدمجة عمداً، فلا تحتاج تثبيت أي حزمة اختبار.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import make_icon                                               # noqa: E402


def _frame_stats(image: Image.Image) -> tuple[float, int]:
    """نسبة البكسلات الحبريّة، وعدد مقاطع الحبر المتّصلة أفقيّاً."""
    px = image.convert("RGBA").load()
    w, h = image.size
    ink = runs = 0
    for y in range(h):
        lit = False
        for x in range(w):
            r, g, b, a = px[x, y]
            on = a > 128 and (r + g + b) / 3 > 150
            ink += on
            runs += on and not lit
            lit = on
    return ink / (w * h), runs


class PathParsing(unittest.TestCase):
    """المُسطِّح هو قلب المولّد: إن انكسر خرجت الأيقونة لطخةً."""

    def test_only_supported_commands_in_the_wordmark(self):
        # لا أقواس (A/a) في المخطوطة، وهو ما يجعل المُسطِّح الصغير كافياً.
        letters = set()
        for d in make_icon.WORDMARK + [make_icon.NOTCH]:
            letters |= {c for c in d if c.isalpha()}
        self.assertTrue(letters <= set("MmLlHhVvCcSsZz"),
                        f"أمر مسار غير مدعوم: {sorted(letters)}")

    def test_unknown_command_is_rejected(self):
        with self.assertRaises(ValueError):
            make_icon.flatten("M0,0A1 1 0 0 1 2,2Z")

    def test_absolute_and_relative_commands(self):
        # مربّع ١٠×١٠ مرسوم بأوامر مطلقة، وآخر مثله بأوامر نسبيّة
        a = make_icon.flatten("M0,0 H10 V10 H0 Z")
        b = make_icon.flatten("m0,0 l10,0 l0,10 l-10,0 z")
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        for contour in (a[0], b[0]):
            self.assertEqual(
                [(round(x, 6), round(y, 6)) for x, y in contour[:4]],
                [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])

    def test_smooth_cubic_mirrors_the_previous_control_point(self):
        explicit = make_icon.flatten("M0,0 C0,10 10,10 10,0 C10,-10 20,-10 20,0Z")
        smooth = make_icon.flatten("M0,0 C0,10 10,10 10,0 S20,-10 20,0Z")
        self.assertEqual(len(explicit[0]), len(smooth[0]))
        for (x1, y1), (x2, y2) in zip(explicit[0], smooth[0]):
            self.assertAlmostEqual(x1, x2, places=6)
            self.assertAlmostEqual(y1, y2, places=6)

    def test_geometry_fills_the_declared_viewbox(self):
        """أقوى دليل على صحّة التحليل: الحدود تطابق viewBox الأصلي."""
        contours = [c for d in make_icon.WORDMARK for c in make_icon.flatten(d, 8.0)]
        x0, y0, x1, y1 = make_icon._bbox(contours)
        vx, vy, vw, vh = make_icon.VIEWBOX
        self.assertAlmostEqual(x0, vx, delta=0.6)
        self.assertAlmostEqual(y0, vy, delta=0.6)
        self.assertAlmostEqual(x1, vx + vw, delta=0.6)
        self.assertAlmostEqual(y1, vy + vh, delta=0.6)

    def test_multi_subpath_and_contour_counts(self):
        counts = [len(make_icon.flatten(d, 4.0)) for d in make_icon.WORDMARK]
        self.assertEqual(counts, [1, 2, 1, 1])


class Rasteriser(unittest.TestCase):

    def test_nonzero_winding_leaves_a_hole(self):
        outer = [(2, 2), (18, 2), (18, 18), (2, 18)]
        inner = [(6, 6), (6, 14), (14, 14), (14, 6)]        # اتّجاه معاكس
        mask = make_icon.rasterize([outer, inner], 20, 20)
        self.assertEqual(mask.getpixel((4, 10)), 255)        # الحلقة مملوءة
        self.assertEqual(mask.getpixel((10, 10)), 0)         # والوسط مفرَّغ

    def test_ink_mask_has_wordmark_shape(self):
        mask = make_icon.ink_mask("hero", 512)
        px = mask.load()
        lit = sum(px[x, y] > 128
                  for y in range(0, 512, 2) for x in range(0, 512, 2))
        share = lit / (256 * 256)
        self.assertGreater(share, 0.05, "القناع شبه فارغ")
        self.assertLess(share, 0.30, "القناع شبه مملوء")
        # المخطوطة عريضة: تمتدّ على أغلب ما بين هامشَي التخطيط.
        # الهامش الحاليّ ٢٠٪ فيبقى للحبر نحو ٦٠٪ من الضلع، فنشترط ٥٥٪.
        cols = [x for x in range(512) if any(px[x, y] > 128 for y in range(512))]
        self.assertGreater(max(cols) - min(cols), 512 * 0.55)

    def test_inner_counter_reads_as_ground(self):
        """الفراغ داخل الشعار (notch) يبقى بلون الأرضية لا بلون الحبر."""
        spec = make_icon.LAYOUTS["hero"]
        scale, ox, oy = make_icon._placement(spec["view"], spec["margin"], 512)
        mask = make_icon.ink_mask("hero", 512)
        cx, cy = int(371 * scale + ox), int(198 * scale + oy)
        self.assertEqual(mask.getpixel((cx, cy)), 0, "الفراغ الداخلي مملوء")
        # الفواصل نسبيّة إلى مقياس الرسم لا مطلقة بالبكسل: كانت ثابتة
        # عند ٢٨ بكسلاً، فلمّا وُسِّع الهامش تقلّص الرسم، فوقعت الفواصل
        # خارج جوار الفتحة. الفتحة نفسها نحو ٣٧ وحدة سعةً، فنُبعد بها.
        dist = int(round(30 * scale))
        for dx, dy in ((0, -dist), (0, dist), (-dist, 0), (dist, 0)):
            self.assertEqual(mask.getpixel((cx + dx, cy + dy)), 255,
                             "الحبر المحيط بالفراغ مفقود")


class GeneratedIcon(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ico = Image.open(make_icon.OUT_ICO)
        cls.built = make_icon.frames()

    def test_every_expected_size_is_embedded(self):
        self.assertEqual(sorted(self.ico.ico.sizes()),
                         [(s, s) for s in make_icon.SIZES])

    def test_no_frame_is_blank_or_uniform(self):
        for size, frame in zip(make_icon.SIZES, self.built):
            with self.subTest(size=size):
                self.assertEqual(frame.size, (size, size))
                coverage, runs = _frame_stats(frame)
                self.assertGreater(coverage, 0.04, "لا حبر في الأيقونة")
                self.assertLess(coverage, 0.40, "الأيقونة لطخة مصمتة")
                # لطخة واحدة تعطي مقطعاً واحداً في كل سطر؛ المخطوطة أكثر
                # تفصيلاً. الحدّ ‎١٫٠× ‎لا ‎١٫٢×‎ بعدما وُسِّع الهامش: صار في
                # كل سطر أسطرٌ فارغة أكثر، وليست إشارةَ لطخة.
                self.assertGreater(runs, size * 1.0, "الحبر كتلة واحدة")
                self.assertGreater(len(frame.convert("RGB").getcolors(1 << 16)), 8)

    def test_frames_use_the_new_palette(self):
        big = self.built[-1].convert("RGB")
        colours = {c for _, c in big.getcolors(1 << 16)}
        self.assertIn(_rgb(make_icon.GROUND), colours)
        self.assertIn(_rgb(make_icon.INK), colours)
        # لا أثر للأحمر القديم ‎#8f1d13‎
        self.assertNotIn((143, 29, 19), colours)

    def test_no_frame_carries_a_rim(self):
        """لا خيطَ ذهبيّاً حول الأيقونة في أيّ مقاس.

        كانت الحاشية تُرسم في المقاسات الكبيرة، وهي stroke محيطٌ
        بالأيقونة لا تريده الواجهة. فالأرضيةُ الداكنة وحدها هي الصدَفة،
        ويُتحقَّق من ذلك بغياب لون الذهب عن الإطار كلِّه.
        """
        for size, frame in zip(make_icon.SIZES, self.built):
            with self.subTest(size=size):
                colours = {c for _, c in frame.convert("RGB").getcolors(1 << 16)}
                self.assertNotIn(_rgb(make_icon.RIM), colours,
                                 "عادت الحاشية الذهبية إلى الأيقونة")

    def test_corners_are_rounded(self):
        big = self.built[-1].convert("RGBA")
        for x, y in ((0, 0), (255, 0), (0, 255), (255, 255)):
            self.assertEqual(big.getpixel((x, y))[3], 0, "الزوايا غير مُدوَّرة")

    def test_committed_ico_matches_the_generator(self):
        """الملف المرفوع يجب أن يكون ناتجَ السكربت الحالي لا نسخةً قديمة."""
        for size, frame in zip(make_icon.SIZES, self.built):
            with self.subTest(size=size):
                self.ico.size = (size, size)
                self.ico.load()
                a = self.ico.convert("RGBA").tobytes()
                b = frame.convert("RGBA").tobytes()
                self.assertEqual(len(a), len(b))
                drift = sum(abs(p - q) for p, q in zip(a, b)) / len(a)
                self.assertLess(drift, 3.0, "أعِد توليد الأيقونة: python tools/make_icon.py")


class GeneratedSvg(unittest.TestCase):

    def test_favicon_is_in_sync_with_the_generator(self):
        on_disk = make_icon.OUT_SVG.read_text(encoding="utf-8")
        self.assertEqual(on_disk, make_icon.svg_markup())

    def test_favicon_carries_the_calligraphy_not_a_glyph(self):
        svg = make_icon.OUT_SVG.read_text(encoding="utf-8")
        for d in make_icon.WORDMARK:
            self.assertIn(d, svg)
        self.assertIn(make_icon.NOTCH, svg)
        self.assertNotIn("<text", svg)
        self.assertNotIn("#8f1d13", svg)
        for colour in (make_icon.GROUND, make_icon.INK):
            self.assertIn(colour, svg)
        # ولا حاشيةَ ذهبية فيها، كالأيقونة سواء
        self.assertNotIn("stroke=", svg)
        self.assertNotIn(make_icon.RIM, svg)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


if __name__ == "__main__":
    unittest.main()
