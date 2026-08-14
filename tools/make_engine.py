"""
يولّد quran-engine.js من الصفحة الأصلية حرفياً.

النسخ اليدوي لهذا الكود خطر: نطاقات مثل [ؐ-ًؚ-ٟ]
مكتوبة بعلامات تشكيل حقيقية، وإعادة كتابتها تُعيد ترتيبها بصرياً
فتتغيّر حدود النطاق بصمت — فيطابق النطاقُ الحروفَ كلَّها بدل العلامات.
لذلك تُقتطع الأسطر من الملف الأصلي كما هي بايتاً ببايت.

تنبيه: كان هذا استخراجاً لمرة واحدة، وقد عُدّل المحرّك بعده باليد
(المطبَّع المحسوب مسبقاً في buildIndex، وحدود المواضع في
collectQuotes). فتشغيل هذا الملف اليوم يطرح ذلك كلَّه ويعود
بالمحرّك إلى صورته الأولى. لا يُشغَّل؛ وإنما يُحدَّث TAIL أدناه
لتبقى الواجهة البرمجية المعلنة مطابقة لما في المحرّك.
"""
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])          # الصفحة قبل الجراحة
target = Path(sys.argv[2])          # quran-engine.js

lines = source.read_text(encoding="utf-8").split("\n")

# الحدود نفسها المستعملة في extract_engine.py
assert lines[982].startswith("/* ==================== تدقيق الآيات"), lines[982]
assert lines[1234] == "}", repr(lines[1234])
assert lines[1267].startswith("/* إحالات الحواشي"), lines[1267]
assert lines[1339] == "}", repr(lines[1339])

block_a = lines[984:1235]     # بعد سطر العنوان والتعليق، حتى نهاية diffWords
block_b = lines[1267:1340]    # footnoteRefs .. stitchQuotes

body = "\n".join(block_a + [""] + block_b)

# الفهرس العام كان متغيّراً في الصفحة اسمه quran؛ يصير داخلياً هنا.
assert "QURAN_KEY" not in body
body, hits = re.subn(r"\bquran\b", "INDEX", body)
print(f"استُبدل {hits} إشارة إلى الفهرس العام")

# إزاحة سطرين داخل الغلاف
body = "\n".join(("  " + ln) if ln.strip() else ln for ln in body.split("\n"))

HEAD = '''/* ============================================================
   محرّك تدقيق الآيات — منطق خالص لا يلمس الواجهة.

   فُصل عن الصفحة عمداً: هذا هو الجزء الذي لا يجوز أن يخطئ، وهو
   الوحيد الذي تغطّيه اختبارات آلية (tests/quran-engine.test.mjs).
   يعمل داخل المتصفح وداخل Node على السواء.

   تحذير لمن يعدّل هذا الملف: نطاقات علامات التشكيل مكتوبة بعلامات
   حقيقية لا برموز \\uXXXX. لا تُعِد كتابتها يدوياً — النسخ واللصق
   يُعيد ترتيب العلامات بصرياً فتنقلب حدود النطاق وتُطابق الحروفَ
   كلَّها. عدِّل الاختبارات أولاً، فهي تكشف هذا فوراً.
   ============================================================ */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.QuranEngine = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* الفهرس المبني من نصّ المصحف. يُضبط مرة واحدة عبر loadData. */
  var INDEX = null;

'''

TAIL = '''

  /* ============================================================
     كم موضعاً يرد فيه هذا المقطع؟

     كثير من المقاطع يتكرّر في المصحف: «ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ»
     في ستة مواضع، و«فَبِأَىِّ ءَالَآءِ رَبِّكُمَا تُكَذِّبَانِ» في إحدى وثلاثين.
     فالبحث يجد أوّلها، ونسبةُ المقطع إليه جزمٌ بما لا يُعلم.
     النصّ نفسه واحد في كل المواضع، فتصحيحه سليم؛ إنما رقم الآية
     هو الذي لا يجوز الجزم به. لذلك يُعدّ عدد المواضع ليُمتنع عن
     إضافة الرقم حين يزيد على واحد.

     يتوقّف العدّ عند cap: الغرض تمييز الواحد من المتعدّد لا الإحصاء.
     ============================================================ */
  function countPlaces(nq, cap) {
    cap = cap || 8;
    if (!INDEX || !nq || nq.length < 10) return 0;
    var n = 0;
    for (var i = 0; i < INDEX.length && n < cap; i++) {
      var s = INDEX[i], at = s.norm.indexOf(nq);
      while (at >= 0 && n < cap) { n++; at = s.norm.indexOf(nq, at + 1); }
    }
    return n;
  }

  /* ============================================================
     ما يستحقّ أن يُعرض في قائمة التدقيق.

     «قال تعالى» لا حدّ لآخره في النصّ، فيلتقط ما بعده إلى آخر
     السطر: الآيةَ ثم كلامَ المؤلف بعدها، وربما اسمَ من ينقل عنه.
     فإن لم يكن في الملتقَط شيء من القرآن أصلاً — لا موضعٌ عُرف
     ولا آيةٌ قريبة — فليس هذا موضع تدقيق، وإنما هو كلام المؤلف.

     أما ما بين ﴿ ﴾ فقد قصده كاتب الوثيقة آيةً وأعلن قصده بالقوسين،
     فيبقى محفوظاً ولو لم يُعرف — لأن عدم معرفته خبرٌ في نفسه.
     ============================================================ */
  function worthShowing(kind, a) {
    if (!a) return false;
    if (a.ref) return true;
    if (kind === "brace") return true;
    return !!a.near;
  }

  /* ==================== الواجهة البرمجية ==================== */
  function setIndex(index) { INDEX = index; return INDEX; }
  function getIndex() { return INDEX; }
  /* يبني الفهرس ويضبطه معاً — فصلهما مصدر أخطاء صامتة */
  function loadData(data) { return setIndex(buildIndex(data)); }

  return {
    QMARK: QMARK, VNUM: VNUM, MARK_STD: MARK_STD, MARK_SKIP: MARK_SKIP,
    normChar: normChar, normMap: normMap, qNorm: qNorm,
    normalMarks: normalMarks, markKey: markKey, bareCompare: bareCompare,
    shape: shape, diffWords: diffWords,
    buildIndex: buildIndex, setIndex: setIndex, getIndex: getIndex,
    loadData: loadData,
    refFromRange: refFromRange, expandRef: expandRef, surahByName: surahByName,
    locateByFootnote: locateByFootnote, locate: locate, nearest: nearest,
    countPlaces: countPlaces,
    cleanQuote: cleanQuote, analyse: analyse,
    toLatin: toLatin, footnoteRefs: footnoteRefs,
    findBraceQuotes: findBraceQuotes, collectQuotes: collectQuotes,
    worthShowing: worthShowing,
    stitchQuotes: stitchQuotes
  };
});
'''

target.write_text(HEAD + body + TAIL, encoding="utf-8")
print(f"كُتب {target.name} — {len(target.read_bytes())} بايت")
