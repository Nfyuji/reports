/** قائمة المدارس والرقم الوزاري — اختيار منسدل يعبّئ الرقم تلقائياً */
window.SCHOOLS = [
  { name: "المتوسطه الخامسة والعشرون بخميس مشيط", type: "بنات", ministry: "63637" },
  { name: "الروضة العاشره بالخميس", type: "بنات", ministry: "19053" },
  { name: "ابتدائية الرصراص الثانية بالخميس", type: "بنات", ministry: "63557" },
  { name: "الابتدائية الثالثة والخمسون بالخميس", type: "بنات", ministry: "16251" },
  { name: "المتوسطة الثامنة عشر بخميس مشيط", type: "بنات", ministry: "63198" },
  { name: "الثانوية الخامسة عشر بخميس مشيط - مسارات", type: "بنات", ministry: "3963550" },
  { name: "الروضة التاسعة بالخميس + الطفولة المبكرة بالروضة التاسعة بخميس مشيط", type: "بنات", ministry: "69023" },
  { name: "الإبتدائية الخامسة والأربعون بالخميس", type: "بنات", ministry: "63656" },
  { name: "ابتدائية الوقبة", type: "بنات", ministry: "62634" },
  { name: "ابتدائية الفاروق", type: "بنين", ministry: "61695" },
  { name: "ابتدائية زيد بن حارثة للطفولة المبكرة بالخميس + الروضة الملحقة", type: "بنات", ministry: "162719" },
  { name: "ثانوية عبدالعزيز الخويطر - مسارات", type: "بنين", ministry: "162072" },
  { name: "متوسطة عمرو بن العاص + ابتدائية تحفيظ الندوة", type: "بنين", ministry: "61392" },
  { name: "ابتدائية الرصراص الأولى بالخميس", type: "بنات", ministry: "62914" },
  { name: "متوسطه وثانوية الوقبه بخميس مشيط", type: "بنات", ministry: "63163" },
  { name: "متوسطة الهرير + ابتدائية العباس بن عبدالمطلب", type: "بنين", ministry: "61385" },
  { name: "متوسطة وثانوية الهرير بخميس مشيط", type: "بنات", ministry: "63152" },
  { name: "ثانوية البيهقي - مسارات", type: "بنين", ministry: "161002" },
  { name: "ابتدائية الهرير الأولى", type: "بنات", ministry: "62699" },
  { name: "الإبتدائية السادسة والعشرون بالخميس", type: "بنات", ministry: "62820" },
  { name: "ابتدائية عدي بن حاتم", type: "بنين", ministry: "61216" },
];

/**
 * يربط قائمة منسدلة باسم المدرسة مع حقل الرقم الوزاري.
 * selectEl: عنصر <select>
 * ministryEl: عنصر إدخال الرقم الوزاري
 * customInputEl: اختياري — حقل نص حر إن اختار "أخرى"
 */
window.bindSchoolSelect = function bindSchoolSelect(selectEl, ministryEl, customInputEl) {
  if (!selectEl || !ministryEl) return;

  // املأ الخيارات مرة واحدة
  if (!selectEl.dataset.filled) {
    selectEl.innerHTML = "";
    const opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "— اختر المدرسة —";
    selectEl.appendChild(opt0);

    window.SCHOOLS.forEach((s, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = `${s.name} (${s.type})`;
      opt.dataset.name = s.name;
      opt.dataset.ministry = s.ministry;
      selectEl.appendChild(opt);
    });

    const other = document.createElement("option");
    other.value = "__other__";
    other.textContent = "أخرى (كتابة يدوية)";
    selectEl.appendChild(other);
    selectEl.dataset.filled = "1";
  }

  function apply() {
    const v = selectEl.value;
    if (v === "__other__") {
      if (customInputEl) {
        customInputEl.hidden = false;
        customInputEl.focus();
      }
      ministryEl.readOnly = false;
      return;
    }
    if (customInputEl) customInputEl.hidden = true;
    ministryEl.readOnly = true;
    if (v === "") {
      ministryEl.value = "";
      return;
    }
    const s = window.SCHOOLS[Number(v)];
    if (!s) return;
    ministryEl.value = s.ministry;
    if (customInputEl) customInputEl.value = s.name;
  }

  selectEl.addEventListener("change", apply);

  /** يضبط القائمة حسب اسم محفوظ مسبقاً */
  selectEl.setFromName = function setFromName(name) {
    const n = (name || "").trim();
    if (!n) {
      selectEl.value = "";
      if (customInputEl) {
        customInputEl.value = "";
        customInputEl.hidden = true;
      }
      return;
    }
    const idx = window.SCHOOLS.findIndex((s) => s.name === n || n.includes(s.name) || s.name.includes(n));
    if (idx >= 0) {
      selectEl.value = String(idx);
      ministryEl.value = window.SCHOOLS[idx].ministry;
      if (customInputEl) {
        customInputEl.value = window.SCHOOLS[idx].name;
        customInputEl.hidden = true;
      }
    } else {
      selectEl.value = "__other__";
      if (customInputEl) {
        customInputEl.hidden = false;
        customInputEl.value = n;
      }
    }
  };

  selectEl.getSchoolName = function getSchoolName() {
    const v = selectEl.value;
    if (v === "__other__") return (customInputEl && customInputEl.value.trim()) || "";
    if (v === "") return (customInputEl && customInputEl.value.trim()) || "";
    const s = window.SCHOOLS[Number(v)];
    return s ? s.name : "";
  };
};
