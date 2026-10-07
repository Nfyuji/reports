(() => {
  const state = {
    filename: "",
    path: "",
    cover: {},
    observations: [],
    photos: [], // {id, src, name}
  };

  const $ = (sel) => document.querySelector(sel);
  const toastEl = $("#toast");
  const savingEl = $("#saving");

  function toast(msg, type = "ok") {
    toastEl.hidden = false;
    toastEl.className = `toast show ${type}`;
    toastEl.textContent = msg;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 3200);
  }

  function setSaving(on, msg) {
    savingEl.classList.toggle("is-on", !!on);
    savingEl.hidden = !on;
    if (msg) {
      const p = savingEl.querySelector("p");
      if (p) p.textContent = msg;
    }
  }

  document.querySelectorAll(".step").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".step").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`#panel-${btn.dataset.panel}`).classList.add("active");
    });
  });

  function todayDateStr() {
    const d = new Date();
    return `${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`;
  }

  function fillCover(cover) {
    state.cover = { ...cover };
    $("#fTitle").value = cover.title || "";
    $("#fSchool").value = cover.school || "";
    $("#fMinistry").value = cover.ministry_no || "";
    $("#fEngineer").value = cover.engineer || "";
    $("#fDate").value = cover.date || todayDateStr();
  }

  function readCover() {
    return {
      title: $("#fTitle").value.trim(),
      school: $("#fSchool").value.trim(),
      ministry_no: $("#fMinistry").value.trim(),
      engineer: $("#fEngineer").value.trim(),
      date: $("#fDate").value.trim() || todayDateStr(),
    };
  }

  let dragNoteIndex = null;

  function renderNotes() {
    const list = $("#notesList");
    list.innerHTML = "";
    state.observations.forEach((text, i) => {
      const li = document.createElement("li");
      li.className = "note-item";
      li.draggable = true;
      li.dataset.index = String(i);
      li.innerHTML = `
        <span class="handle" title="اسحب لإعادة الترتيب">⋮⋮</span>
        <textarea data-i="${i}" rows="2">${escapeAttr(text)}</textarea>
        <button type="button" class="rm" title="حذف" data-rm="${i}">×</button>
      `;
      li.addEventListener("dragstart", () => {
        dragNoteIndex = i;
        li.style.opacity = "0.5";
      });
      li.addEventListener("dragend", () => {
        li.style.opacity = "1";
        dragNoteIndex = null;
      });
      li.addEventListener("dragover", (e) => e.preventDefault());
      li.addEventListener("drop", (e) => {
        e.preventDefault();
        const to = Number(li.dataset.index);
        if (dragNoteIndex === null || dragNoteIndex === to) return;
        const item = state.observations.splice(dragNoteIndex, 1)[0];
        state.observations.splice(to, 0, item);
        renderNotes();
      });
      list.appendChild(li);
    });

    list.querySelectorAll("textarea").forEach((inp) => {
      inp.addEventListener("input", () => {
        state.observations[Number(inp.dataset.i)] = inp.value;
      });
    });
    list.querySelectorAll("[data-rm]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.observations.splice(Number(btn.dataset.rm), 1);
        renderNotes();
      });
    });
  }

  $("#btnAddNote").addEventListener("click", () => {
    state.observations.push("");
    renderNotes();
    const inputs = $("#notesList").querySelectorAll("textarea");
    inputs[inputs.length - 1]?.focus();
  });

  $("#btnApplyNotes")?.addEventListener("click", () => {
    const raw = ($("#notesBulk")?.value || "").replace(/\r\n/g, "\n").trim();
    if (!raw) {
      toast("الصق الملاحظات أولاً", "error");
      return;
    }
    const notes = raw
      .split("\n")
      .map((x) => x.replace(/^[\-•●▪►\d\)\(\.\s]+/, "").trim())
      .filter(Boolean);
    state.observations = notes;
    renderNotes();
    toast(`تم تطبيق ${notes.length} ملاحظة`);
  });

  $("#btnClearNotes")?.addEventListener("click", () => {
    if (!state.observations.length) return;
    if (confirm("مسح كل الملاحظات؟")) {
      state.observations = [];
      renderNotes();
    }
  });

  async function runAiFill(localOnly) {
    const text = ($("#aiRawText")?.value || "").trim();
    if (!text) {
      toast("الصق البيانات أولاً", "error");
      return;
    }
    setSaving(true, localOnly ? "جاري التحليل المحلي…" : "جاري التحليل عبر Gemini…");
    try {
      const res = await fetch("/api/ai/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, local_only: !!localOnly, use_today_date: true }),
      });
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل التحليل");
      const cover = data.cover || {};
      cover.date = todayDateStr();
      fillCover(cover);
      if (Array.isArray(data.observations) && data.observations.length) {
        state.observations = data.observations
          .map((x) => String(x).replace(/^[\-•●▪►§·\*\d\)\(\.\s]+/, "").trim())
          .filter(Boolean);
        renderNotes();
        if ($("#notesBulk")) {
          $("#notesBulk").value = state.observations.join("\n");
        }
      }
      // حفظ مباشر → الشريحة الثانية تُحدَّث كنقاط في الملف
      setSaving(true, "جاري حفظ الملاحظات كنقاط في الشريحة الثانية…");
      const saveRes = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cover: readCover(),
          observations: state.observations.map((t) => t.trim()).filter(Boolean),
          photo_ids: state.photos.map((p) => p.id),
        }),
      });
      if (saveRes.status === 401) {
        location.href = "/login";
        return;
      }
      const saved = await saveRes.json();
      if (!saved.ok) throw new Error(saved.error || "فشل الحفظ");
      state.filename = saved.filename;
      $("#fileBadge").textContent = "نسختي: " + saved.filename;
      const src = data.source === "gemini" ? "Gemini" : "محلي";
      toast(`تم التحديث (${src}) — ${state.observations.length} نقطة في الشريحة الثانية`);
    } catch (err) {
      toast(err.message || "خطأ في التعبئة", "error");
    } finally {
      setSaving(false);
    }
  }

  $("#btnAiFill")?.addEventListener("click", () => runAiFill(false));
  $("#btnLocalFill")?.addEventListener("click", () => runAiFill(true));

  let dragPhotoId = null;

  function updatePhotoMeta() {
    const n = state.photos.length;
    $("#photoCount").textContent = `${n} صورة`;
    $("#slideEstimate").textContent = `= ${n ? Math.ceil(n / 6) : 0} شريحة صور`;
  }

  function renderPhotos() {
    const grid = $("#photoGrid");
    grid.innerHTML = "";
    state.photos.forEach((ph, i) => {
      const card = document.createElement("div");
      card.className = "photo-card";
      card.draggable = true;
      card.dataset.id = ph.id;
      card.innerHTML = `
        <img src="${ph.src}" alt="${escapeAttr(ph.name || "صورة")}" />
        <span class="badge">${i + 1}</span>
        <button type="button" class="x" data-del="${ph.id}" title="حذف">×</button>
      `;
      card.addEventListener("dragstart", () => {
        dragPhotoId = ph.id;
        card.style.opacity = "0.55";
      });
      card.addEventListener("dragend", () => {
        card.style.opacity = "1";
        dragPhotoId = null;
      });
      card.addEventListener("dragover", (e) => e.preventDefault());
      card.addEventListener("drop", (e) => {
        e.preventDefault();
        if (!dragPhotoId || dragPhotoId === ph.id) return;
        const from = state.photos.findIndex((p) => p.id === dragPhotoId);
        const to = state.photos.findIndex((p) => p.id === ph.id);
        if (from < 0 || to < 0) return;
        const item = state.photos.splice(from, 1)[0];
        state.photos.splice(to, 0, item);
        renderPhotos();
      });
      grid.appendChild(card);
    });

    grid.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.photos = state.photos.filter((p) => p.id !== btn.dataset.del);
        renderPhotos();
      });
    });
    updatePhotoMeta();
  }

  async function uploadFiles(fileList) {
    const files = [...fileList].filter((f) => f.type.startsWith("image/"));
    if (!files.length) {
      toast("لم يتم اختيار صور صالحة", "error");
      return;
    }
    const fd = new FormData();
    files.forEach((f) => fd.append("photos", f));
    setSaving(true, "جاري رفع الصور…");
    try {
      const res = await fetch("/api/photos/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل الرفع");
      state.photos.push(...data.photos);
      renderPhotos();
      toast(`تمت إضافة ${data.photos.length} صورة`);
    } catch (err) {
      toast(err.message || "خطأ في الرفع", "error");
    } finally {
      setSaving(false, "جاري الحفظ على ملف التقرير…");
    }
  }

  $("#photoInput").addEventListener("change", (e) => {
    uploadFiles(e.target.files);
    e.target.value = "";
  });

  $("#btnClearPhotos").addEventListener("click", () => {
    if (!state.photos.length) return;
    if (confirm("مسح كل الصور من القائمة؟")) {
      state.photos = [];
      renderPhotos();
    }
  });

  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
    });
  });
  dz.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  async function loadReport() {
    try {
      const res = await fetch("/api/report");
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل التحميل");
      state.filename = data.filename;
      state.path = data.path;
      $("#fileBadge").textContent = "نسختي: " + (data.filename || "report.pptx");
      fillCover(data.cover || {});
      // دائماً تاريخ اليوم عند فتح الجلسة (يوم العمل)
      $("#fDate").value = todayDateStr();
      state.observations = Array.isArray(data.observations) ? [...data.observations] : [];
      renderNotes();
      if ($("#notesBulk")) {
        $("#notesBulk").value = state.observations.join("\n");
      }
      state.photos = (data.photos || []).map((p) => ({
        id: p.id,
        src: p.src,
        name: p.name || "صورة",
      }));
      renderPhotos();
      toast("تم تحميل نسختك الخاصة");
    } catch (err) {
      toast(err.message || "خطأ في التحميل", "error");
    }
  }

  async function saveReport() {
    setSaving(true, "جاري الحفظ على نسختك الخاصة…");
    try {
      const payload = {
        cover: readCover(),
        observations: state.observations.map((t) => t.trim()).filter(Boolean),
        photo_ids: state.photos.map((p) => p.id),
      };
      const res = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        location.href = "/login";
        return;
      }
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "فشل الحفظ");
      state.filename = data.filename;
      $("#fileBadge").textContent = "نسختي: " + data.filename;
      toast(`تم الحفظ على نسختك — ${data.photo_count} صورة`);
    } catch (err) {
      toast(err.message || "خطأ في الحفظ", "error");
    } finally {
      setSaving(false);
    }
  }

  $("#btnReload").addEventListener("click", loadReport);
  $("#btnSave").addEventListener("click", saveReport);
  $("#btnDownload").addEventListener("click", () => {
    window.location.href = "/api/download";
  });

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  loadReport();
})();
