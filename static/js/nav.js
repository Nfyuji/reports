/* قائمة الجوال المشتركة للشريط العلوي */
(function () {
  const toggle = document.getElementById("navToggle");
  const actions = document.getElementById("topActions");
  if (!toggle || !actions) return;

  function closeMenu() {
    actions.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "فتح القائمة");
  }

  function openMenu() {
    actions.classList.add("is-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "إغلاق القائمة");
  }

  toggle.addEventListener("click", () => {
    if (actions.classList.contains("is-open")) closeMenu();
    else openMenu();
  });

  window.addEventListener("resize", () => {
    if (window.matchMedia("(min-width: 768px)").matches) {
      actions.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });
})();
