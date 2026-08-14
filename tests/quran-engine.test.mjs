/* اختبارات محرّك تدقيق الآيات.
   تشغيل:  node --test tests/
   لا تحتاج أي حزمة خارجية — مُشغّل الاختبارات مدمج في Node 18 فأحدث. */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const assets = join(here, "..", "src", "masih", "assets");
const require = createRequire(import.meta.url);

const QE = require(join(assets, "quran-engine.js"));
const QURAN = JSON.parse(readFileSync(join(assets, "quran.json"), "utf8"));
QE.loadData(QURAN);

const surah = (id) => QURAN.find((s) => s.id === id);
const verse = (sid, vid) => surah(sid).verses.find((v) => v.id === vid).text;

/* الفاتحة ٢ — نصّ عثماني كما هو في قاعدة البيانات */
const FATIHA_2 = verse(1, 2);
/* البقرة ٢٥٥ (آية الكرسي) — أول مقطع منها */
const KURSI = verse(2, 255);

// ===================================================== سلامة النطاقات
/* هذا الاختبار يحرس أخطر عطب في المحرّك: نطاقات علامات التشكيل
   مكتوبة بعلامات حقيقية، وأي إعادة كتابة لها تُعيد ترتيبها بصرياً
   فينقلب النطاق [ؐ-ًؚ-ٟ] إلى ما يبتلع الحروف كلَّها.
   حينها يُرجع qNorm نصاً فارغاً، فلا تُطابَق أي آية، ويقول البرنامج
   عن كل اقتباس «ليست قرآناً» — عطب صامت لا يظهر إلا هنا. */
test("نطاق علامات التشكيل لا يبتلع الحروف", () => {
  for (const letter of "ابتثجحخدذرزسشصضطظعغفقكلمنهوي") {
    assert.equal(QE.QMARK.test(letter), false,
      `الحرف ${letter} صُنّف علامةَ تشكيل — النطاق منقلب`);
  }
  for (const mark of ["ً", "َ", "ّ", "ْ", "ٰ",
                      "ۖ", "ۡ", "ـ"]) {
    assert.equal(QE.QMARK.test(mark), true,
      `U+${mark.codePointAt(0).toString(16)} لم يُصنَّف علامة`);
  }
});

test("التطبيع يُبقي هيكل الكلمة ولا يُفرغه", () => {
  const norm = QE.qNorm(FATIHA_2);
  assert.ok(norm.length > 10, `التطبيع أعاد "${norm}" — النصّ ضاع`);
  assert.ok(/[ء-ي]/.test(norm), "لم يبقَ أي حرف عربي بعد التطبيع");
  assert.equal(/[ً-ْٰ]/.test(norm), false,
    "بقيت علامات تشكيل بعد التطبيع");
});

// ===================================================== الرسمان
test("الرسم الإملائي يُطابق الرسم العثماني", () => {
  /* «الرحمن» بالإملاء الحديث مقابل «ٱلرَّحۡمَٰنِ» بالرسم العثماني */
  assert.equal(QE.qNorm("الرحمن"), QE.qNorm("ٱلرَّحۡمَٰنِ"));
  assert.equal(QE.qNorm("العالمين"), QE.qNorm("ٱلۡعَٰلَمِينَ"));
  assert.equal(QE.qNorm("الحمد لله رب العالمين"), QE.qNorm(FATIHA_2));
});

/* حدّ معروف موثّق، لا عطب:
   المصحف يكتب «إبراهيم» في بعض المواضع بياء صغيرة معلّقة (U+06E7)
   بدل الياء الكاملة: إِبۡرَٰهِـۧمَ. والياء الصغيرة علامةٌ يُسقطها
   التطبيع، فيصير المطبَّع «برهم» لا «برهيم». فمن كتب الكلمة إملائياً
   لم تُطابق حرفياً في تلك المواضع.
   الأثر محدود: الآية تُوجَد على مسار المطابقة الجزئية ويُعرض تصحيحها،
   لكنها تُصنَّف «مقطوعة» بدل «مطابقة تماماً». */
test("الياء الصغيرة المعلّقة: حدّ موثّق في التطبيع", () => {
  assert.equal(QE.qNorm("إِبۡرَٰهِيمَ"), QE.qNorm("إبراهيم"),
    "الرسم بالياء الكاملة يجب أن يُطابق الإملائي");
  assert.notEqual(QE.qNorm("إِبۡرَٰهِـۧمَ"), QE.qNorm("إبراهيم"),
    "تغيّر سلوك الياء الصغيرة — راجع التوثيق في README");
});

test("التاء المربوطة والألف المقصورة والهمزات تُوحَّد", () => {
  assert.equal(QE.qNorm("رحمة"), QE.qNorm("رحمه"));
  assert.equal(QE.qNorm("موسى"), QE.qNorm("موسي"));
  assert.equal(QE.qNorm("مؤمن"), QE.qNorm("مومن"));
});

// ===================================================== مفتاح المقارنة
test("markKey يحفظ التشكيل ويُسقط علامات الوقف", () => {
  /* التشكيل فرق حقيقي: به يُميَّز «مطابق تماماً» من «يختلف في التشكيل» */
  assert.notEqual(QE.markKey("رَبِّ"), QE.markKey("رب"));
  /* علامات التجويد والوقف ليست فرقاً */
  assert.equal(QE.markKey("رَبِّۖ"), QE.markKey("رَبِّ"));
  assert.equal(QE.markKey("رَبِّـ"), QE.markKey("رَبِّ"));
});

test("markKey يوحّد صور التنوين المختلفة في قاعدة البيانات", () => {
  /* Tanzil تُرمّز بعض المواضع برموز بديلة؛ اصطلاح ترميزي لا فرق إملائي */
  assert.equal(QE.markKey("ٖ"), QE.markKey("ٍ"));
  assert.equal(QE.markKey("ٗ"), QE.markKey("ً"));
  assert.equal(QE.markKey("ٞ"), QE.markKey("ٌ"));
  assert.equal(QE.markKey("ۡ"), QE.markKey("ْ"));
});

// ===================================================== تحديد الموضع
test("يجد الآية ويُرجع سورتها ورقمها", () => {
  const ref = QE.locate(QE.qNorm(FATIHA_2));
  assert.ok(ref, "لم يُعثر على الفاتحة ٢");
  assert.equal(ref.sid, 1);
  assert.equal(ref.from, 2);
  assert.equal(ref.to, 2);
});

test("يجد آية طويلة من وسط المصحف", () => {
  const ref = QE.locate(QE.qNorm(KURSI));
  assert.ok(ref, "لم يُعثر على آية الكرسي");
  assert.equal(ref.sid, 2);
  assert.equal(ref.from, 255);
});

test("المقتبس الممتدّ على آيتين يُرجع نطاقاً", () => {
  const two = verse(1, 2) + " " + verse(1, 3);
  const ref = QE.locate(QE.qNorm(two));
  assert.ok(ref, "لم يُعثر على الآيتين معاً");
  assert.equal(ref.from, 2);
  assert.equal(ref.to, 3);
  assert.equal(ref.segs.length, 2);
});

// ===================================================== التحليل
test("الاقتباس السليم يُصنَّف مطابقاً تماماً", () => {
  const a = QE.analyse(FATIHA_2, "brace");
  assert.equal(a.kind, "full");
  assert.equal(QE.bareCompare(a.quoted), QE.bareCompare(a.ref.canonical),
    "نصّ سليم صُنّف مختلفاً");
});

test("كلمة محرَّفة تجعل الاقتباس مقطوعاً لا مطابقاً", () => {
  /* نُفسد كلمة في وسط آية طويلة، كما يفعل المسح الضوئي الرديء.
     الآية الطويلة مقصودة: التحليل يشترط تطابق أربع كلمات فأكثر
     قبل أن يجزم بالموضع، فالآية القصيرة لا تكفيه. */
  const words = KURSI.split(" ");
  words[6] = "الضضضين";
  const a = QE.analyse(words.join(" "), "brace");
  assert.notEqual(a.kind, "full", "التحريف مرّ على أنه مطابق تام");
  assert.ok(a.ref, "لم يُقترح تصحيح للنصّ المحرَّف");
  assert.equal(a.ref.sid, 2, "نُسب التصحيح إلى سورة أخرى");
});

test("المقطع الصحيح يُعرف ولو كان بعض آية", () => {
  /* المطابقة الحرفية تعمل على أي مقطع يتجاوز عشرة أحرف مطبَّعة،
     فلا يُشترط اقتباس الآية كاملة. أما حدّ الأربع كلمات فيحكم
     مسار المطابقة التقريبية وحده. */
  const a = QE.analyse("الحمد لله رب", "brace");
  assert.equal(a.kind, "full");
  assert.equal(a.ref.sid, 1);
  assert.equal(a.ref.from, 2);
});

test("المقطع الأقصر من الحدّ لا يُنسب", () => {
  /* أقلّ من عشرة أحرف مطبَّعة: كثير من الكلمات القصيرة يرد في
     المصحف وفي غيره، فنسبتها إليه تُنتج تصحيحات خاطئة. */
  assert.equal(QE.locate(QE.qNorm("الحمد")), null);
});

test("النصّ غير القرآني لا يُنسب إلى المصحف", () => {
  const a = QE.analyse("هذا كلام عادي كتبه مؤلف الكتاب في مقدمته الطويلة", "brace");
  assert.equal(a.kind, "none");
  assert.equal(a.ref, undefined);
});

test("اختلاف التشكيل وحده يُرصد ولا يُعدّ تحريفاً", () => {
  const bare = FATIHA_2.replace(/[ً-ْ]/g, "");
  const a = QE.analyse(bare, "brace");
  assert.equal(a.kind, "full", "النصّ بلا تشكيل لم يُعرف");
  assert.notEqual(QE.bareCompare(a.quoted), QE.bareCompare(a.ref.canonical),
    "فرق التشكيل لم يُرصد");
});

// ===================================================== الأقواس
test("قوس رقم الآية لا يُقرأ اقتباساً", () => {
  const text = `﴿${FATIHA_2}﴾ ﴿٢﴾ ثم كلام بعده`;
  const found = QE.findBraceQuotes(text);
  assert.equal(found.length, 1, "رقم الآية عُدّ اقتباساً مستقلاً");
  assert.equal(found[0].raw.trim(), FATIHA_2);
});

test("رقم الآية داخل الاقتباس لا يقطعه", () => {
  const text = `﴿${verse(1, 2)} ﴿٢﴾ ${verse(1, 3)}﴾`;
  const found = QE.findBraceQuotes(text);
  assert.equal(found.length, 1, "الاقتباس انقطع عند رقم الآية");
  assert.ok(found[0].raw.includes(verse(1, 3)), "ضاع ما بعد رقم الآية");
});

test("قوس بلا إغلاق لا يبتلع بقية الوثيقة", () => {
  const found = QE.findBraceQuotes("﴿ آية بلا إغلاق ثم كلام كثير");
  assert.equal(found.length, 0);
});

// ===================================================== لمّ المقطوع
test("الاقتباس المقطوع بين صفحتين يُلمّ", () => {
  const half = FATIHA_2.split(" ");
  const cut = half.slice(0, 2).join(" ") + " <!-- صفحة 4 --> " + half.slice(2).join(" ");
  const st = QE.stitchQuotes(`﴿${cut}﴾`);
  assert.equal(st.count, 1, "لم يُرصد الاقتباس المقطوع");
  const a = QE.analyse(QE.findBraceQuotes(st.text)[0].raw, "brace");
  assert.equal(a.kind, "full", "الاقتباس بعد اللمّ لم يُطابق");
});

// ===================================================== الحواشي
test("إحالة الحاشية تُقرأ وتُنسب إلى سورتها", () => {
  const refs = QE.footnoteRefs("قال تعالى كذا (١) سورة البقرة: ٢٥٥");
  assert.ok(refs["1"], "لم تُقرأ الإحالة");
  assert.equal(refs["1"].sid, 2);
  assert.equal(refs["1"].ayah, 255);
});

test("الإحالة إلى غير سورة تُرفض", () => {
  /* «المستدرك» كتاب لا سورة — لا يجوز أن يُبنى عليه تصحيح آية */
  const refs = QE.footnoteRefs("انظر (٢) المستدرك: ٣٤٥");
  assert.equal(refs["2"], undefined);
});

test("اسم السورة يُطابق بأل التعريف وبدونها", () => {
  assert.ok(QE.surahByName("البقرة"));
  assert.ok(QE.surahByName("بقرة"));
  assert.ok(QE.surahByName("سورة البقرة"));
  assert.equal(QE.surahByName("زقزقة"), null);
});

// ===================================================== الفروق
test("المقارنة ترصد الناقص والزائد والمختلف تشكيلاً", () => {
  const parts = QE.diffWords("الحمد لله رب زائدة", "الحمد لله رب العالمين");
  const kinds = parts.map((p) => p.t);
  assert.ok(kinds.includes("same"), "لم تُرصد كلمة مطابقة");
  assert.ok(kinds.includes("extra"), "لم تُرصد الكلمة الزائدة");
  assert.ok(kinds.includes("missing"), "لم تُرصد الكلمة الناقصة");
});

test("المقارنة تفصل فرق التشكيل عن فرق الكلمة", () => {
  const parts = QE.diffWords("رب", "رَبِّ");
  assert.equal(parts.length, 1);
  assert.equal(parts[0].t, "diac", "فرق التشكيل صُنّف تبديلَ كلمة");
});

test("أرقام الآيات في التصحيح لا تُحسب فروقاً", () => {
  const parts = QE.diffWords("الحمد لله", "الحمد لله ﴿٢﴾");
  assert.equal(parts.filter((p) => p.t === "missing").length, 0,
    "رقم الآية عُدّ كلمة ناقصة");
  assert.equal(parts.filter((p) => p.t === "vnum").length, 1);
});

// ===================================================== الرصد في النص
test("«قال تعالى» يُرصد كموضع تدقيق", () => {
  const quotes = QE.collectQuotes(`قال تعالى: ${FATIHA_2}`);
  assert.ok(quotes.some((q) => q.kind === "trigger"), "لم يُرصد موضع «قال تعالى»");
});

/* ============================================================
   الموضع في الوثيقة.

   عليه يقوم التصحيح الشامل: يستبدل بالموضع لا بالبحث عن النصّ،
   فلا يُصيب موضعاً غير الذي عُرضت بطاقتُه. فإن انزاح الموضع
   حرفاً واحداً أفسد الاستبدالُ ما حوله.
   ============================================================ */
test("كل موضع يحمل حدوده في الوثيقة", () => {
  const text = `تمهيد ﴿${FATIHA_2}﴾ ثم قال تعالى: ${KURSI} وهذا بيان.`;
  const quotes = QE.collectQuotes(text);
  assert.ok(quotes.length >= 2, "لم تُرصد المواضع");
  for (const q of quotes) {
    assert.equal(typeof q.start, "number", "موضع بلا بداية");
    assert.equal(text.slice(q.start, q.end), q.raw,
      `حدود الموضع لا تُطابق نصّه: «${q.raw.slice(0, 30)}»`);
  }
});

test("المقطع المكرَّر: حدود كل موضع تخصّه وحده", () => {
  /* فخّ indexOf: المقطع نفسه مرتين، فالبحث الأعمى يجد الأول دائماً */
  const text = `﴿${FATIHA_2}﴾ كلام بينهما ﴿${verse(1, 3)}﴾`;
  const q = QE.collectQuotes(text);
  assert.equal(q.length, 2);
  assert.ok(q[1].start > q[0].end, "الموضع الثاني لم يُرصد بعد الأول");
  assert.equal(text.slice(q[1].start, q[1].end), q[1].raw);
});

// ============================================ ما يستحقّ العرض
/* ============================================================
   قاعدة العرض، بشطريها.

   قسم التدقيق للقرآن وحده. فلا يُعرض موضع إلا إذا أمكن نسبته إلى
   المصحف: بموضع عُرف (ref) أو بأقرب آية وجدها nearest (near).
   وما سوى ذلك يسقط صامتاً، سواء أجاء بين ﴿ ﴾ أم بعد «قال تعالى».

   والشطر الثاني حارسٌ ألّا يبتلع الشطرُ الأول الآيةَ المحرَّفة:
   ما أفسده المسح الضوئي قرآنٌ وإن تحرّف، ولا بدّ أن يبقى معروضاً
   ليُصحَّح.
   ============================================================ */
test("كلام المؤلف بعد «قال تعالى» لا يصير موضع تدقيق", () => {
  const prose = "ذكره الشيخ عبد الرحمن بن ناصر السعدي في تيسير الكريم الرحمن";
  const a = QE.analyse(prose, "trigger");
  assert.equal(a.kind, "none", "نُسب كلام المؤلف إلى المصحف");
  assert.equal(QE.worthShowing("trigger", a), false,
    "كلام المؤلف ما زال يُعرض موضعَ تدقيق");
});

test("ما بين القوسين لا يُعرض إن لم يُنسب إلى المصحف", () => {
  /* اسم رجل بين قوسين مزخرفين: القوسان في غير موضعهما، ولا عمل
     للقارئ في بطاقة تقول «ليس من القرآن» إلا تجاهلها. */
  const a = QE.analyse("عبد الله بن عباس رضي الله عنهما حبر الأمة", "brace");
  assert.equal(a.kind, "none");
  assert.equal(a.ref, undefined, "نُسب اسم الرجل إلى موضع من المصحف");
  assert.equal(a.near, null, "نُسب اسم الرجل إلى آية قريبة");
  assert.equal(QE.worthShowing("brace", a), false,
    "ما بين القوسين ما زال يُعرض ولو لم يكن قرآناً");
});

test("اسم السورة بين القوسين لا يصير بطاقة", () => {
  const a = QE.analyse("سورة البقرة", "brace");
  assert.equal(QE.worthShowing("brace", a), false);
});

test("الآية المحرَّفة تبقى معروضة على كل حال", () => {
  const words = KURSI.split(" ");
  words[6] = "الضضضين";
  const a = QE.analyse(words.join(" "), "trigger");
  assert.ok(QE.worthShowing("trigger", a), "الآية المحرَّفة أُسقطت من القائمة");
});

test("الآية التي أفسدها المسح حتى لم تُنسب موضعاً تبقى بأقرب آية", () => {
  /* كلّ كلمة رابعة مفسَدة: لا يبقى ركضٌ من أربع كلمات متتابعة
     فيسقط مسارُ المطابقة الجزئية ولا ref لها. ومع ذلك هي قرآن،
     يجدها nearest، فيجب أن تبقى معروضةً قابلةً للتصحيح — وإلا
     كان إسقاطُ ما ليس بقرآن قد أسقط معه الآيةَ المحرَّفة. */
  const words = KURSI.split(" ").map((w, i) => (i % 4 === 0 ? "خخخخ" + i : w));
  const a = QE.analyse(words.join(" "), "brace");
  assert.equal(a.ref, undefined, "غيّرت المطابقة الجزئية سلوكها — راجع الحالة");
  assert.ok(a.near, "لم تُوجد أقرب آية للنصّ المحرَّف");
  assert.equal(a.near.sid, 2);
  assert.equal(a.near.from, 255);
  assert.equal(QE.worthShowing("brace", a), true,
    "الآية المحرَّفة سقطت مع سقوط ما ليس بقرآن");
});

/* ============================================================
   حدّ «أقرب آية».

   كان ثلاثَ كلمات فحسب، فكان يلتقط ما ليس بقرآن: «عبد الله بن
   عباس رضي الله عنهما» تشترك مع التوبة ١٠٠ في «الله» و«رضي»
   و«عنهم»، فتُنسب إليها وتُعرض بطاقةً لا عمل للقارئ فيها.
   ============================================================ */
test("«أقرب آية» لا تلتقط الأسماء ولا الثناء ولا الحديث", () => {
  const junk = [
    "عبد الله بن عباس رضي الله عنهما حبر الأمة",
    "رضي الله عنه وأرضاه ونفعنا بعلمه في الدنيا والآخرة",
    "قال رسول الله صلى الله عليه وسلم إنما الأعمال بالنيات",
    "ذكره الشيخ عبد الرحمن بن ناصر السعدي في تيسير الكريم الرحمن",
    "سورة البقرة",
  ];
  for (const text of junk)
    assert.equal(QE.nearest(QE.qNorm(text)), null,
      `نُسب إلى المصحف ما ليس منه: «${text}»`);
});

// ================================================= تعدّد المواضع
/* أساس الأمان في «صحّح كل الآيات»: كثير من المقاطع يتكرّر، فنصّه
   معلوم ورقمه مظنون. من دون هذا العدّ يُلصق البرنامج برقم آية
   قد يكون خاطئاً في وثيقة علمية. */
test("يعدّ مواضع المقطع المتكرّر", () => {
  const many = QE.countPlaces(QE.qNorm("الحمد لله رب العالمين"));
  assert.ok(many > 1, `المقطع المتكرّر عُدّ ${many} موضعاً فقط`);
});

test("المقطع الفريد موضع واحد", () => {
  assert.equal(QE.countPlaces(QE.qNorm("قل هو الله احد الله الصمد")), 1);
});

test("العدّ يتوقّف عند السقف ولا يمسح المصحف كلّه", () => {
  /* «فبأي آلاء ربكما تكذبان» وحدها في إحدى وثلاثين موضعاً */
  assert.equal(QE.countPlaces(QE.qNorm("فباي الاء ربكما تكذبان"), 4), 4);
});

test("المقطع القصير لا يُعدّ أصلاً", () => {
  assert.equal(QE.countPlaces(QE.qNorm("الحمد"), 8), 0);
});

// ============================================ الفهرس المسبق
/* nearest كان يطبّع الآيات كلَّها مع كل اقتباس لم يُطابق فتتجمّد
   النافذة. صار المطبَّع يُحسب في buildIndex مرة واحدة، وهذا يحرس
   أن المحسوب مسبقاً هو عين ما كان يُحسب في حينه — فلو افترقا
   تغيّرت نتائج «أقرب آية» بصمت. */
test("نصّ كل آية مطبَّعاً محسوب في الفهرس ومطابق للتطبيع المباشر", () => {
  const index = QE.getIndex();
  let checked = 0;
  for (const s of index) {
    for (const o of s.offs) {
      assert.equal(typeof o.norm, "string",
        `الآية ${s.id}:${o.id} بلا نصّ مطبَّع في الفهرس`);
      assert.equal(o.norm, QE.qNorm(s.orig.slice(o.start, o.end)),
        `المطبَّع المحسوب مسبقاً خالف المباشر عند ${s.id}:${o.id}`);
      checked++;
    }
  }
  assert.equal(checked, 6236);
});

test("«أقرب آية» ما زالت تجد الآية المحرَّفة", () => {
  /* آية أُفسدت كلماتها حتى لم تعُد تُطابق حرفياً */
  const words = KURSI.split(" ");
  words[2] = "الاااه"; words[5] = "الححح"; words[8] = "تااااخذه";
  const near = QE.nearest(QE.qNorm(words.join(" ")));
  assert.ok(near, "لم يُعثر على أقرب آية");
  assert.equal(near.sid, 2);
  assert.equal(near.from, 255);
});

test("سلامة نصّ المصحف المرفق", () => {
  assert.equal(QURAN.length, 114, "عدد السور ليس ١١٤");
  const total = QURAN.reduce((n, s) => n + s.verses.length, 0);
  assert.equal(total, 6236, "عدد الآيات ليس ٦٢٣٦");
});

/* ===================================================== نصّ التصحيح
   buildCorrection يسكن في index.html لا في المحرّك، فيُنتزع منه
   ويُشغَّل ببديلين عن shape و num. والغرض حراسة عطبٍ رآه المستخدم:
   الاقتباس يخرج بقوسين ﴿…﴿٨﴾﴾ لأن رقم الآية الأخيرة كان يُكتب قبل
   القوس الخاتم مباشرة. */
const PAGE = readFileSync(join(assets, "index.html"), "utf8");
const buildCorrection = (() => {
  const at = PAGE.indexOf("function buildCorrection(");
  assert.ok(at > 0, "لم يُعثر على buildCorrection في الصفحة");
  const end = PAGE.indexOf("\n}", at);
  const src = PAGE.slice(at, end + 2);
  return new Function("shape", "num", src + "\nreturn buildCorrection;")(
    (s) => s, (n) => String(n));
})();

const seg = (text, id, full) => ({ text, id, full });

test("الاقتباس لا يخرج بقوسين: لا رقم بعد آخر آية", () => {
  const out = buildCorrection({ canonical: "نص", segs: [seg("الآية", 8, true)] });
  assert.equal(out, "الآية");
  assert.ok(!out.includes("\uFD3F"), `خرج فيه قوس زائد: ${out}`);
});

test("الرقم يفصل بين الآيتين ولا يُختم به", () => {
  const out = buildCorrection({
    canonical: "نص", segs: [seg("الأولى", 5, true), seg("الثانية", 6, true)] });
  assert.equal(out, "الأولى \uFD3F5\uFD3E الثانية");
});

test("المقطع الناقص لا رقم له", () => {
  const out = buildCorrection({
    canonical: "نص", segs: [seg("صدر الآية", 5, false), seg("التالية", 6, true)] });
  assert.equal(out, "صدر الآية التالية");
});

test("المقطع المكرَّر يُصحَّح بلا أرقام أصلاً", () => {
  const out = buildCorrection(
    { canonical: "نص", segs: [seg("الأولى", 5, true), seg("الثانية", 6, true)] }, true);
  assert.equal(out, "الأولى الثانية");
});
