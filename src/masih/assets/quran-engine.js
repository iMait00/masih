/* ============================================================
   محرّك تدقيق الآيات — منطق خالص لا يلمس الواجهة.

   فُصل عن الصفحة عمداً: هذا هو الجزء الذي لا يجوز أن يخطئ، وهو
   الوحيد الذي تغطّيه اختبارات آلية (tests/quran-engine.test.mjs).
   يعمل داخل المتصفح وداخل Node على السواء.

   تحذير لمن يعدّل هذا الملف: نطاقات علامات التشكيل مكتوبة بعلامات
   حقيقية لا برموز \uXXXX. لا تُعِد كتابتها يدوياً — النسخ واللصق
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

  var QMARK=/[ؐ-ًؚ-ٰٟۖ-ۭـࣰ-ࣿ]/;

  function normChar(c){
    if(QMARK.test(c)) return "";
    if(/\s/.test(c)) return " ";
    /* الألف تُسقط من الطرفين: الرسم العثماني يحذفها والإملائي يثبتها
       (ٱلۡكَٰفِرِينَ مقابل الكافرين، وٱلرَّحۡمَٰنِ مقابل الرحمن) */
    if(/[آأإاٱٲٳ]/.test(c)) return "";
    if(c==="ى") return "ي";
    if(c==="ة") return "ه";
    if(c==="ؤ") return "و";
    if(c==="ئ") return "ي";
    if(c==="ء") return "";
    if(/[ء-ي]/.test(c)) return c;
    return "";
  }
  /* تطبيع مع خريطة تُرجع كل حرف مطبَّع إلى موضعه الأصلي */
  function normMap(orig){
    var out="",map=[],prevSpace=true;
    for(var i=0;i<orig.length;i++){
      var r=normChar(orig[i]);
      if(!r) continue;
      if(r===" "){ if(prevSpace) continue; out+=" "; map.push(i); prevSpace=true; continue; }
      out+=r; map.push(i); prevSpace=false;
    }
    while(out.slice(-1)===" "){ out=out.slice(0,-1); map.pop(); }
    return {norm:out,map:map};
  }
  function qNorm(s){ return normMap(s).norm; }
  function bareCompare(s){ return markKey(s); }

  function buildIndex(data){
    return data.map(function(s){
      var offs=[],pos=0,parts=[];
      s.verses.forEach(function(v){
        offs.push({id:v.id,start:pos,end:pos+v.text.length});
        parts.push(v.text); pos+=v.text.length+1;
      });
      var orig=parts.join(" "), nm=normMap(orig);
      /* ============================================================
         نصّ كل آية مطبَّعاً يُحسب هنا مرة واحدة لا عند كل بحث.

         كان nearest يطبّع الآيات الستّ آلاف ومئتين مع كل اقتباس لم
         يُطابق، والتطبيع يمرّ على كل حرف بعدة تعبيرات نمطية — فتُعدّ
         الملايين من العمليات للاقتباس الواحد وتتجمّد النافذة.

         ويُشتقّ من خريطة السورة لا بإعادة تطبيع كل آية على حدة،
         ليبقى المطبَّع هو عينه الذي يبحث فيه locate، فلا يفترق
         الطريقان عند حدود الآيات.
         ============================================================ */
      var p=0;
      offs.forEach(function(o){
        while(p<nm.map.length && nm.map[p]<o.start) p++;
        var i0=p;
        while(p<nm.map.length && nm.map[p]<o.end) p++;
        o.norm=nm.norm.slice(i0,p);
      });
      return {id:s.id,name:s.name,orig:orig,offs:offs,norm:nm.norm,map:nm.map};
    });
  }
  /* يبني المرجع من نطاق أحرف داخل سورة، مقتصراً على المقتبس */
  function refFromRange(s,oS,oE){
    var sidx=INDEX.indexOf(s);
    while(oS>0 && !/\s/.test(s.orig[oS-1])) oS--;
    while(oE<s.orig.length && !/\s/.test(s.orig[oE])) oE++;
    var from=null,to=null,segs=[];
    for(var k=0;k<s.offs.length;k++){
      var o=s.offs[k];
      if(o.end<=oS || o.start>=oE) continue;
      if(from===null) from=o.id;
      to=o.id;
      segs.push({id:o.id,
                 full:(oS<=o.start && oE>=o.end),
                 text:s.orig.slice(Math.max(oS,o.start),Math.min(oE,o.end)).trim()});
    }
    return {surah:s.name,sid:s.id,sidx:sidx,oS:oS,oE:oE,from:from,to:to,segs:segs,canonical:s.orig.slice(oS,oE)};
  }
  /* الكلمات التي لم تُطابق ليست زائدة بالضرورة، بل قد تكون
     تحريفاً في المسح الضوئي لبقية الآية. فيُمدّ المقابل القرآني
     بقدرها — دون تجاوز حدود الآية — بدل اقتطاع الآية عندها. */
  function expandRef(ref,wBefore,wAfter){
    if(!ref || (!wBefore && !wAfter)) return ref;
    var s=INDEX[ref.sidx]; if(!s) return ref;
    var oS=ref.oS, oE=ref.oE, lo=0, hi=s.orig.length;
    s.offs.forEach(function(o){
      if(o.id===ref.from) lo=o.start;
      if(o.id===ref.to)   hi=o.end;
    });
    var i;
    for(i=0;i<wAfter && oE<hi;i++){
      while(oE<hi && /\s/.test(s.orig[oE])) oE++;
      while(oE<hi && !/\s/.test(s.orig[oE])) oE++;
    }
    for(i=0;i<wBefore && oS>lo;i++){
      while(oS>lo && /\s/.test(s.orig[oS-1])) oS--;
      while(oS>lo && !/\s/.test(s.orig[oS-1])) oS--;
    }
    return refFromRange(s,oS,oE);
  }

  /* أسماء السور للتحقق من صحة إحالة الحاشية */
  function surahByName(nm){
    if(!INDEX || !nm) return null;
    var target=qNorm(nm).replace(/^سوره\s*/,"").replace(/^سورت\s*/,"").trim();
    if(target.length<2) return null;
    for(var i=0;i<INDEX.length;i++){
      var n=qNorm(INDEX[i].name);
      if(n===target || n==="ل"+target || target==="ل"+n) return INDEX[i];
    }
    return null;
  }
  /* يبحث عن المقتبس داخل الآية التي أحالت إليها الحاشية (وجارتيها) */
  function locateByFootnote(nq,sObj,ayah){
    if(!nq || nq.length<8) return null;
    var lo=Math.max(1,ayah-1), hi=ayah+1, ranges=[];
    sObj.offs.forEach(function(o){ if(o.id>=lo && o.id<=hi) ranges.push(o); });
    if(!ranges.length) return null;
    var vStart=ranges[0].start, vEnd=ranges[ranges.length-1].end;
    var idx=sObj.norm.indexOf(nq);
    while(idx>=0){
      var oS=sObj.map[idx];
      if(oS>=vStart && oS<vEnd)
        return refFromRange(sObj,oS,sObj.map[idx+nq.length-1]+1);
      idx=sObj.norm.indexOf(nq,idx+1);
    }
    return null;
  }

  /* يحدّد الموضع ويستخرج المقابل الأصلي لنفس المقطع، لا الآية كاملة */
  function locate(nq){
    if(!INDEX || nq.length<10) return null;
    for(var i=0;i<INDEX.length;i++){
      var s=INDEX[i], idx=s.norm.indexOf(nq);
      if(idx<0) continue;
      return refFromRange(s, s.map[idx], s.map[idx+nq.length-1]+1);
    }
    return null;
  }
  /* ============================================================
     أقرب آية — للنصّ الذي أفسده المسح الضوئي حتى لم يُطابق حرفياً.

     الحدّ هنا حدُّ نسبةٍ إلى المصحف، فلا يجوز أن يكون رخواً: كل
     موضع تُرجعه هذه الدالة يصير بطاقةً أمام المستخدم. وكان الحدّ
     «ثلاث كلمات» فحسب، فكان يلتقط ما ليس بقرآن أصلاً: «رضي الله
     عنهما» و«عبد الله بن عباس» تشترك مع آيات طوال في كلمات
     شائعة — «الله» و«رضي» و«عنهم» — فتُنسب إلى التوبة ١٠٠.

     فالشرط الآن شرطان معاً:
       • أن يُوجد في الآية أكثرُ كلمات المقتبس (لا بعضها)
       • وأن يكون المقتبس شيئاً معتبَراً من الآية نفسها، أو أن
         تبلغ الكلمات المتطابقة ثمانياً — وهو قدرٌ لا تبلغه
         المصادفةُ في كلام غير قرآني.

     والاسمُ يسقط لأنه لا يغطّي من الآية الطويلة إلا خُمسها، وكلامُ
     المؤلف يسقط لأن أكثر كلماته ليست فيها. وتبقى الآية المحرَّفة:
     كلماتها كلها من الآية، وهي أكثرُها.
     ============================================================ */
  var NEAR_QUERY_SHARE=0.6;   /* من كلمات المقتبس */
  var NEAR_VERSE_SHARE=0.4;   /* من كلمات الآية */
  var NEAR_STRONG=8;          /* كلمات متطابقة تُغني عن شرط التغطية */

  function nearest(nq){
    if(!INDEX) return null;
    var words=nq.split(" ").filter(function(w){return w.length>2;});
    if(words.length<2) return null;
    var best=null,bestScore=0,bestSeg=0;
    for(var i=0;i<INDEX.length;i++){
      var s=INDEX[i];
      for(var k=0;k<s.offs.length;k++){
        var o=s.offs[k], score=0;
        /* المطبَّع جاهز من buildIndex؛ والاشتقاق هنا احتياطٌ لفهرس
           بُني بنسخة أقدم، ويُحفظ فلا يُعاد حسابه مرة أخرى */
        var seg=(o.norm!==undefined)?o.norm:(o.norm=qNorm(s.orig.slice(o.start,o.end)));
        var segWords=seg.split(" ").filter(Boolean).length;
        for(var w=0;w<words.length;w++) if(seg.indexOf(words[w])>=0) score++;
        /* عند التساوي تُقدَّم الآية الأقصر: تغطيتها للمقتبس أعلى */
        if(score>bestScore || (score===bestScore && score>0 && segWords<bestSeg)){
          bestScore=score; bestSeg=segWords;
          best={surah:s.name,sid:s.id,from:o.id,to:o.id,canonical:s.orig.slice(o.start,o.end)};
        }
      }
    }
    if(!best || bestScore<3) return null;
    if(bestScore < Math.ceil(words.length*NEAR_QUERY_SHARE)) return null;
    if(bestScore < NEAR_STRONG &&
       bestScore < Math.ceil(bestSeg*NEAR_VERSE_SHARE)) return null;
    return best;
  }

  /* تنظيف الاقتباس من مخلّفات المسح الضوئي */
  function cleanQuote(raw){
    return raw
      .replace(/\uFD3F[\d\u0660-\u0669]{1,3}\uFD3E/g,"")   /* أرقام آيات سبق إدراجها */
      .replace(/<!--[\s\S]*?-->/g,"")
      .replace(/!\[[^\]]*\]\([^)]*\)/g,"")
      .replace(/[-–—]\s*[\d٠-٩]{1,4}\s*[-–—]/g,"")
      .replace(/^[\s،.:؛]+|[\s،.:؛]+$/g,"")
      .replace(/\s+/g," ").trim();
  }

  /* التحليل: مطابقة كاملة، أو مقطوعة/مقحمة، أو ليست قرآناً */
  function analyse(raw,srcKind){
    var clean=cleanQuote(raw);
    var nm=normMap(clean), nq=nm.norm;
    var full=locate(nq);
    if(full) return {kind:"full",clean:clean,quoted:clean,ref:full};

    var words=nq.split(" ").filter(Boolean);
    if(words.length<3) return {kind:"none",clean:clean,quoted:clean};

    function rawSlice(fromWord,toWord){
      var nStart=fromWord? words.slice(0,fromWord).join(" ").length+1 : 0;
      var nEnd=words.slice(0,toWord).join(" ").length;
      var oS=nm.map[nStart], oE=nm.map[nEnd-1]+1;
      while(oS>0 && !/\s/.test(clean[oS-1])) oS--;
      while(oE<clean.length && !/\s/.test(clean[oE])) oE++;
      return clean.slice(oS,oE);
    }

    var best=null,h,c;
    for(var e=words.length-1;e>=3;e--){
      h=locate(words.slice(0,e).join(" "));
      if(h){ best={hit:h,from:0,to:e,count:e}; break; }
    }
    for(var s0=1;s0<=words.length-3;s0++){
      h=locate(words.slice(s0).join(" "));
      if(h){
        c=words.length-s0;
        if(!best || c>best.count) best={hit:h,from:s0,to:words.length,count:c};
        break;
      }
    }
    if(best && best.count>=4){
      var quoted=rawSlice(best.from,best.to);
      /* بعد «قال تعالى» يتلو الآيةَ كلامُ المؤلف عادةً، فيُقتصر على الآية */
      if(srcKind==="trigger" && best.from===0)
        return {kind:"full",clean:clean,quoted:quoted,ref:best.hit};
      /* داخل القوسين: كل ما لم يُطابق يُفترض تحريفاً في الآية نفسها */
      var wide=expandRef(best.hit,best.from,words.length-best.to);
      return {kind:"partial",clean:clean,quoted:clean,
              ref:wide,covered:best.count,total:words.length};
    }

    return {kind:"none",clean:clean,quoted:clean,near:nearest(nq)};
  }
  /* رسم الحروف عثماني، وعلامات التنوين والسكون بشكلها المعتاد */
  function shape(txt){ return normalMarks(txt); }

  /* ============================================================
     ليست هذه صور تنوين في المصحف المطبوع — المصحف يرسم التنوين
     بشكله المعروف. لكن قاعدة البيانات الرقمية (Tanzil) تُرمِّز
     بعض مواضع التنوين والسكون برموز يونيكود مختلفة:
       U+0656 مكان ٍ   ·   U+0657 مكان ً
       U+065E مكان ٌ   ·   U+06E1 مكان ْ
     وهي اصطلاح ترميزي لا فرق إملائي. فتُردّ إلى صورتها المعروفة
     قبل المقارنة وقبل الإدراج. أما رسم الحروف — الألف الخنجرية
     وألف الوصل — فرسم عثماني حقيقي يُحفظ كما هو.
     ============================================================ */
  var MARK_STD={
    "\u0656":"\u064D",  /* ٖ → ٍ */
    "\u0657":"\u064B",  /* ٗ → ً */
    "\u065E":"\u064C",  /* ٞ → ٌ */
    "\u06E1":"\u0652"   /* ۡ → ْ */
  };
  /* علامات تجويد ووقف لا أثر لها في صحة النص */
  var MARK_SKIP=/[\u0640\u06D6-\u06DD\u06DE-\u06E0\u06E2-\u06E4\u06E7-\u06ED]/g;

  function normalMarks(txt){
    var o="";
    for(var i=0;i<txt.length;i++){ var c=txt[i]; o += (MARK_STD[c]||c); }
    return o;
  }
  /* مفتاح المقارنة: يوحّد صور العلامة الواحدة ويسقط علامات التجويد */
  function markKey(s){
    return normalMarks(s).replace(/\uFD3F[\d\u0660-\u0669]{1,3}\uFD3E/g,"")
                         .replace(MARK_SKIP,"").replace(/\s+/g,"");
  }

  /* ==================== مقارنة الفروق ==================== */
  /* لا يجوز تغليف حرف مفرد داخل الكلمة العربية بوسم مستقل،
     فذلك يقطع الوصل ويظهر الحرف منفصلاً. التمييز على مستوى
     الكلمة كاملة فقط، حفاظاً على تشكّل الحروف. */
  var VNUM=/^\uFD3F[\d\u0660-\u0669]+\uFD3E$/;
  function diffWords(a,b){
    var keep=function(w){ return w && (VNUM.test(w) || markKey(w).length>0); };
    var A=a.split(/\s+/).filter(keep), B=b.split(/\s+/).filter(keep);
    var na=A.map(qNorm), nb=B.map(qNorm);
    var m=A.length,n=B.length,dp=[],i,j;
    for(i=0;i<=m;i++){ dp.push(new Array(n+1).fill(0)); }
    for(i=m-1;i>=0;i--) for(j=n-1;j>=0;j--)
      dp[i][j]= na[i]===nb[j] ? dp[i+1][j+1]+1 : Math.max(dp[i+1][j],dp[i][j+1]);
    var out=[]; i=0; j=0;
    while(i<m&&j<n){
      if(na[i]===nb[j]){ out.push({t:markKey(A[i])===markKey(B[j])?"same":"diac",a:A[i],b:B[j]}); i++; j++; }
      else if(dp[i+1][j]>=dp[i][j+1]){ out.push({t:"extra",a:A[i]}); i++; }
      else { out.push({t:VNUM.test(B[j])?"vnum":"missing",b:B[j]}); j++; }
    }
    while(i<m) out.push({t:"extra",a:A[i++]});
    while(j<n){ out.push({t:VNUM.test(B[j])?"vnum":"missing",b:B[j]}); j++; }
    return out;
  }

  /* إحالات الحواشي: رقم يلي الآية ويشير في الحاشية إلى السورة والآية */
  function footnoteRefs(text){
    var map={},m;
    var re=/[(\[]\s*([\d\u0660-\u0669]{1,3})\s*[)\]]\s*(?:سورة\s+)?([\u0621-\u064A\u0670 ]{3,25}?)\s*[:：،,\/]?\s*(?:ال)?(?:آية|الآيتان|الآيات)?\s*[:：]?\s*([\d\u0660-\u0669]{1,3})/g;
    while((m=re.exec(text))!==null){
      var sObj=surahByName(m[2]);
      /* تُرفض الإحالة إن لم تكن إلى سورة فعلية — «المستدرك ٣» ليس مرجعاً قرآنياً */
      if(!sObj) continue;
      map[toLatin(m[1])]={surah:sObj.name,sid:sObj.id,ayah:parseInt(toLatin(m[3]),10)};
    }
    return map;
  }
  function toLatin(n){ return String(n).replace(/[\u0660-\u0669]/g,function(d){return String(d.charCodeAt(0)-0x0660);}); }

  /* ماسح الأقواس: يتجاوز أقواس أرقام الآيات ﴿٣﴾ ولا يعدّها
     إغلاقاً للاقتباس، وإلا انقطعت الآية عند رقمها بعد تصحيحها. */
  var VNUM_TOKEN=/^\uFD3F[\d\u0660-\u0669]{1,3}\uFD3E/;
  function findBraceQuotes(text){
    var out=[], i=0;
    while(i<text.length){
      var start=text.indexOf("\uFD3F",i);
      if(start<0) break;
      var lead=VNUM_TOKEN.exec(text.slice(start));
      if(lead){ i=start+lead[0].length; continue; }     /* قوس رقم آية */
      var j=start+1, close=-1;
      while(j<text.length){
        if(text[j]==="\uFD3F"){
          var inner=VNUM_TOKEN.exec(text.slice(j));
          if(inner){ j+=inner[0].length; continue; }    /* رقم آية داخلي */
          break;                                        /* قوس فتح جديد */
        }
        if(text[j]==="\uFD3E"){ close=j; break; }
        j++;
      }
      if(close<0){ i=start+1; continue; }
      out.push({raw:text.slice(start+1,close),start:start,end:close});
      i=close+1;
    }
    return out;
  }

  /* رصد المواضع */
  function collectQuotes(text){
    var out=[],m,seen={};
    findBraceQuotes(text).forEach(function(b){
      var r=b.raw.trim();
      var after=/^\s*[(\[]?\s*([\d\u0660-\u0669]{1,3})/.exec(text.slice(b.end+1));
      /* ============================================================
         start و end حدّا ما بين القوسين في الوثيقة.

         يُحفظان ليكون الاستبدال بالموضع لا بالبحث عن النصّ: المقطع
         الواحد قد يرد مرتين، فبحث indexOf الأعمى كان يصحّح أوّل
         موضع ويترك الذي عُرضت بطاقتُه. وكذلك المقطع الذي هو بعضُ
         مقطع آخر، كان يُصاب داخله فيُفسده.
         ============================================================ */
      if(r && !seen[r]){ seen[r]=1; out.push({raw:r,kind:"brace",fn:after?toLatin(after[1]):null,
                                              start:b.start+1,end:b.end}); }
    });
    var trig=/(?:قال\s+(?:الله\s+)?تعالى|قوله\s+تعالى|قال\s+عز\s+وجل|يقول\s+(?:الله\s+)?تعالى|قال\s+سبحانه)\s*[:：]?\s*[«"']?\s*([^\n﴿]{8,400})/g;
    while((m=trig.exec(text))!==null){
      var capAt=trig.lastIndex-m[1].length;
      var seg=m[1].replace(/[»"'].*$/,"").trim();
      var lead=m[1].indexOf(seg);
      if(seg && !seen[seg]){ seen[seg]=1;
        out.push({raw:seg,kind:"trigger",start:capAt+lead,end:capAt+lead+seg.length}); }
    }
    return out;
  }

  /* ============================================================
     ما يستحقّ أن يُعرض في قائمة التدقيق.

     القاعدة واحدة لا استثناء فيها: لا يُعرض موضع إلا إذا أمكن
     نسبته إلى المصحف — إمّا بموضع عُرف (ref) وإمّا بأقرب آية
     وجدها nearest (near). وما سوى ذلك يسقط صامتاً.

     ولا فرق في ذلك بين ما جاء بين ﴿ ﴾ وما جاء بعد «قال تعالى».
     كان ما بين القوسين يُعرض ولو لم يُعرف، بحجة أن القوسين إعلانُ
     قصدٍ من الكاتب. وكانت ثمرة ذلك بطاقةً تقول «ليس من القرآن»
     ليس فيها للقارئ عمل إلا تجاهلها: اسمُ رجل بين قوسين، أو اسمُ
     سورة، أو كلامُ المؤلف يتلو الآية. وقسم التدقيق للقرآن وحده،
     فما لم يُنسب إليه فليس من شأنه.

     والآيةُ التي أفسدها المسح الضوئي تبقى: هي قرآن وإن تحرّفت،
     وتُعرف بـ near فيُعرض تصحيحها. فالحذف يقع على ما لا قرآن فيه
     أصلاً، لا على ما ضاعت منه بعض حروفه.
     ============================================================ */
  function worthShowing(kind,a){
    if(!a) return false;
    return !!(a.ref || a.near);
  }

  /* لمّ الاقتباسات المقطوعة بين صفحتين */
  function stitchQuotes(text){
    var n=0, quotes=findBraceQuotes(text);
    for(var k=quotes.length-1;k>=0;k--){
      var q=quotes[k];
      if(!/<!--|!\[|[-–—]\s*[\d\u0660-\u0669]{1,4}\s*[-–—]/.test(q.raw)) continue;
      n++;
      var cleaned=q.raw
        .replace(/<!--[\s\S]*?-->/g,"")
        .replace(/!\[[^\]]*\]\([^)]*\)/g,"")
        .replace(/[-–—]\s*[\d\u0660-\u0669]{1,4}\s*[-–—]/g,"")
        .replace(/\s+/g," ").trim();
      text=text.slice(0,q.start+1)+cleaned+text.slice(q.end);
    }
    return {text:text,count:n};
  }

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
