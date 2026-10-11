(() => {
  const SHEET_KEYS = ["OM", "HVAC", "CLEANING"];

  const state = {
    active: "OM",
    header: {},
    sheets: {}, // key -> {meta..., items:[]}
    photos: {
      OM: { board: [], work: [] },
      HVAC: { board: [], work: [] },
      CLEANING: { board: [], work: [] },
    },
  };

  const $ = (s) => document.querySelector(s);
  const toastEl = $("#toast");
  const savingEl = $("#saving");

  function toast(msg, type = "ok") {
    toastEl.hidden = false;
    toastEl.className = `toast show ${type}`;
    toastEl.textContent = msg;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 2800);
  }

  function setSaving(on, msg) {
    savingEl.classList.toggle("is-on", !!on);
    savingEl.hidden = !on;
    const p = savingEl.querySelector("p");
    if (p && msg) p.textContent = msg;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function readHeader() {
    return {
      school: $("#school").value.trim(),
      ministry_no: $("#ministry").value.trim(),
      engineer: $("#engineer").value.trim(),
      provider: $("#provider").value.trim(),
      group_no: $("#group").value.trim(),
      day: Number($("#day").value) || $("#day").value,
      month: $("#month").value.trim().toUpperCase(),
      year: Number($("#year").value) || $("#year").value,
    };
  }

  function fillHeader(h) {
    state.header = h || {};
    $("#school").value = h.school || "";
    $("#ministry").value = h.ministry_no || "";
    $("#engineer").value = h.engineer || "";
    $("#provider").value = h.provider || "";
    $("#group").value = h.group_no || "";
    $("#day").value = h.day || "";
    $("#month").value = h.month || "";
    $("#year").value = h.year || "";
  }

  function currentSheet() {
    return state.sheets[state.active];
  }

  function updateProgress() {
    const sh = currentSheet();
    if (!sh) {
      $("#progress").textContent = "0 / 0";
      return;
    }
    const total = sh.items.length;
    const done = sh.items.filter((i) => i.done).length;
    $("#progress").textContent = `${done} / ${total}`;
  }

  function renderChecks() {
    const sh = currentSheet();
    const list = $("#checkList");
    list.innerHTML = "";
    if (!sh) {
      list.innerHTML = `<li class="check-item"><div class="txt">لا توجد بنود — حدّث الصفحة أو تأكد من رفع قالب الإكسل</div></li>`;
      updateProgress();
      renderThumbs();
      return;
    }

    const labels = {
      OM: ["صور الصيانة", "صورة لوحة + صور أعمال الصيانة"],
      HVAC: ["صور التكييف", "صورة لوحة + صور أعمال التكييف"],
      CLEANING: ["صور نظافة المبنى", "صورة لوحة + صور نظافة المبنى"],
    };
    const [title, hint] = labels[state.active] || ["صور الأعمال", ""];
    $("#workPhotoTitle").textContent = title;
    $("#workPhotoHint").textContent = hint;

    sh.items.forEach((it, idx) => {
      const li = document.createElement("li");
      li.className = "check-item" + (it.done ? " on" : "");
      li.innerHTML = `
        <button type="button" class="done-btn" data-i="${idx}">${it.done ? "تم" : "☐"}</button>
        <div class="txt">${escapeHtml(it.text)}</div>
      `;
      list.appendChild(li);
    });

    list.querySelectorAll(".done-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const i = Number(btn.dataset.i);
        sh.items[i].done = !sh.items[i].done;
        renderChecks();
      });
    });
    updateProgress();
    renderThumbs();
  }

  function renderThumbs() {
    if (!state.photos[state.active]) {
      state.photos[state.active] = { board: [], work: [] };
    }
    const pack = state.photos[state.active];
    const draw = (el, arr, kind) => {
      el.innerHTML = "";
      arr.forEach((p, i) => {
        const d = document.createElement("div");
        d.className = "thumb";
        d.innerHTML = `<img src="${p.src}" alt="" /><button type="button" class="rm" data-kind="${kind}" data-i="${i}">×</button>`;
        el.appendChild(d);
      });
      el.querySelectorAll(".rm").forEach((btn) => {
        btn.addEventListener("click", () => {
          const k = btn.dataset.kind;
          const i = Number(btn.dataset.i);
          state.photos[state.active][k].splice(i, 1);
          renderThumbs();
        });
      });
    };
    draw($("#boardThumbs"), pack.board, "board");
    draw($("#workThumbs"), pack.work, "work");
  }

  async function filesToPhotos(fileList) {
    const out = [];
    for (const f of Array.from(fileList || [])) {
      if (!f.type.startsWith("image/")) continue;
      const src = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result);
        r.onerror = reject;
        r.readAsDataURL(f);
      });
      out.push({ src, name: f.name, file: f });
    }
    return out;
  }

  $("#boardInput").addEventListener("change", async (e) => {
    const photos = await filesToPhotos(e.target.files);
    state.photos[state.active].board.push(...photos);
    e.target.value = "";
    renderThumbs();
  });
  $("#workInput").addEventListener("change", async (e) => {
    const photos = await filesToPhotos(e.target.files);
    state.photos[state.active].work.push(...photos);
    e.target.value = "";
    renderThumbs();
  });

  document.querySelectorAll(".stab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".stab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.active = btn.dataset.key || "OM";
      renderChecks();
    });
  });

  $("#btnAllDone").addEventListener("click", () => {
    const sh = currentSheet();
    if (!sh) return;
    sh.items.forEach((i) => (i.done = true));
    renderChecks();
    toast("تم تعليم كل البنود");
  });
  $("#btnAllClear").addEventListener("click", () => {
    const sh = currentSheet();
    if (!sh) return;
    sh.items.forEach((i) => (i.done = false));
    renderChecks();
  });

  async function uploadPhotos() {
    const fd = new FormData();
    for (const key of SHEET_KEYS) {
      const pack = state.photos[key] || { board: [], work: [] };
      for (const kind of ["board", "work"]) {
        (pack[kind] || []).forEach((p, i) => {
          if (p.file) fd.append(`photo_${key}_${kind}_${i}`, p.file, p.name || "photo.jpg");
          else if (p.id) fd.append(`keep_${key}_${kind}`, p.id);
        });
      }
    }
    const res = await fetch("/api/daily/photos", { method: "POST", body: fd });
    if (res.status === 401) {
      location.href = "/login";
      return null;
    }
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "فشل رفع الصور");
    return data.photo_ids;
  }

  async function saveDaily() {
    setSaving(true, "جاري حفظ الإكسل…");
    try {
      if (!Object.keys(state.sheets).length) {
        throw new Error("لم تُحمَّل بنود التقرير. حدّث الصفحة أولاً");
      }
      const photo_ids = await uploadPhotos();
      if (!photo_ids) return;
      const payload = {
        header: readHeader(),
        sheets: Object.values(state.sheets).map((sh) => ({
          key: sh.key,
          items: sh.items.map((it) => ({ id: it.id, done: !!it.done, done_cell: it.done_cell })),
        })),
        photo_ids,
      };
      const res = await fetch("/api/daily/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        throw new Error("فشل الحفظ (استجابة غير صحيحة من السيرفر)");
      }
      if (!res.ok || !data.ok) throw new Error(data.error || `فشل الحفظ (${res.status})`);
      toast("تم الحفظ في ملف الإكسل ✓");
    } catch (err) {
      console.error(err);
      toast(err.message || "خطأ في الحفظ", "error");
    } finally {
      setSaving(false);
    }
  }

  async function loadDaily() {
    setSaving(true, "جاري التحميل…");
    try {
      const res = await fetch("/api/daily");
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل التحميل");
      fillHeader(data.header || {});
      state.sheets = {};
      (data.sheets || []).forEach((sh) => {
        const key = sh.key === "O&M" ? "OM" : sh.key;
        sh.key = key;
        state.sheets[key] = sh;
        if (!state.photos[key]) state.photos[key] = { board: [], work: [] };
      });
      if (data.photos) {
        for (const rawKey of Object.keys(data.photos)) {
          const key = rawKey === "O&M" ? "OM" : rawKey;
          state.photos[key] = {
            board: (data.photos[rawKey].board || []).map((p) => ({ id: p.id, src: p.src, name: p.name })),
            work: (data.photos[rawKey].work || []).map((p) => ({ id: p.id, src: p.src, name: p.name })),
          };
        }
      }
      if (!state.sheets[state.active]) {
        state.active = SHEET_KEYS.find((k) => state.sheets[k]) || "OM";
      }
      document.querySelectorAll(".stab").forEach((b) => {
        b.classList.toggle("active", b.dataset.key === state.active);
      });
      renderChecks();
      const counts = SHEET_KEYS.map((k) => `${k}:${(state.sheets[k] && state.sheets[k].items.length) || 0}`).join(" ");
      toast(`تم التحميل — ${counts}`);
    } catch (err) {
      toast(err.message || "خطأ", "error");
    } finally {
      setSaving(false);
    }
  }

  $("#btnSave").addEventListener("click", saveDaily);
  $("#btnReload").addEventListener("click", loadDaily);
  $("#btnDownload").addEventListener("click", async () => {
    await saveDaily();
    window.location.href = "/api/daily/download";
  });
  $("#btnToPptx").addEventListener("click", async () => {
    setSaving(true, "جاري إرسال الصور لعرض PowerPoint…");
    try {
      await saveDaily();
      const res = await fetch("/api/daily/to-pptx", { method: "POST" });
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل الإرسال");
      toast(`تم إرسال ${data.photo_count || 0} صورة للعرض`);
      setTimeout(() => (location.href = "/editor"), 700);
    } catch (err) {
      toast(err.message || "خطأ", "error");
    } finally {
      setSaving(false);
    }
  });

  loadDaily();
})();
