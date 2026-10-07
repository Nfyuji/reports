(() => {
  const toastEl = document.getElementById("toast");

  function toast(msg, type = "ok") {
    toastEl.hidden = false;
    toastEl.className = `toast show ${type}`;
    toastEl.textContent = msg;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 2800);
  }

  document.getElementById("passwordForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const current = document.getElementById("pwCurrent").value;
    const new_password = document.getElementById("pwNew").value;
    const confirm = document.getElementById("pwConfirm").value;
    const res = await fetch("/api/admin/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current, new_password, confirm }),
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || "فشل التغيير", "error");
      return;
    }
    toast("تم تغيير كلمة المرور");
    setTimeout(() => location.reload(), 700);
  });

  document.getElementById("templateForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("templateFile");
    if (!fileInput.files?.length) {
      toast("اختر ملف pptx", "error");
      return;
    }
    const fd = new FormData();
    fd.append("template", fileInput.files[0]);
    const res = await fetch("/api/admin/upload-template", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || "فشل رفع القالب", "error");
      return;
    }
    toast("تم رفع القالب بنجاح");
    setTimeout(() => location.reload(), 800);
  });

  document.getElementById("geminiForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const api_key = document.getElementById("geminiKey").value.trim();
    const res = await fetch("/api/admin/gemini-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key }),
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || "فشل الحفظ", "error");
      return;
    }
    toast(api_key ? "تم حفظ مفتاح Gemini" : "تم مسح المفتاح");
    setTimeout(() => location.reload(), 700);
  });

  document.getElementById("createForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const display_name = document.getElementById("newName").value.trim();
    const months = Number(document.getElementById("newMonths").value || 1);
    const res = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name, months }),
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || "فشل الإنشاء", "error");
      return;
    }
    document.getElementById("createdBox").hidden = false;
    document.getElementById("cName").textContent = data.user.display_name;
    document.getElementById("cCode").textContent = data.user.access_code;
    document.getElementById("cExp").textContent = data.user.expires_at;
    toast("تم إنشاء الاشتراك");
    setTimeout(() => location.reload(), 900);
  });

  document.getElementById("btnCopy")?.addEventListener("click", async () => {
    const code = document.getElementById("cCode").textContent;
    try {
      await navigator.clipboard.writeText(code);
      toast("تم نسخ الرقم");
    } catch {
      toast("انسخ الرقم يدوياً", "error");
    }
  });

  document.querySelectorAll(".btn-renew").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const res = await fetch(`/api/admin/users/${id}/renew`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ months: 1 }),
      });
      const data = await res.json();
      if (!data.ok) return toast(data.error || "فشل التجديد", "error");
      toast("تم تجديد شهر");
      location.reload();
    });
  });

  document.querySelectorAll(".btn-toggle").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const res = await fetch(`/api/admin/users/${id}/toggle`, { method: "POST" });
      const data = await res.json();
      if (!data.ok) return toast(data.error || "فشل", "error");
      location.reload();
    });
  });

  document.querySelectorAll(".btn-reset").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("إعادة قالب نظيف لهذا المستخدم؟ سيُستبدل تقريره الحالي.")) return;
      const id = btn.dataset.id;
      const res = await fetch(`/api/admin/reset-user-report/${id}`, { method: "POST" });
      const data = await res.json();
      if (!data.ok) return toast(data.error || "فشل", "error");
      toast("تمت إعادة القالب");
    });
  });
})();
