document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    const old = button.textContent;
    button.textContent = "کپی شد ✓";
    setTimeout(() => (button.textContent = old), 1800);
  } catch (_) {}
});

// بستن منوی دسته‌بندی با کلیک بیرون از آن، کلیک روی لینک‌ها یا Escape.
(() => {
  const closeMenu = () => document.body.classList.remove("menu-open");

  document.addEventListener("click", (event) => {
    if (!document.body.classList.contains("menu-open")) return;
    if (event.target.closest("[data-menu-toggle]")) return;
    if (event.target.closest(".nav")) return;
    closeMenu();
  });

  document.querySelectorAll(".nav a").forEach((link) => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
})();

// اسلایدر: تعویض خودکار هر ۵ ثانیه + فلش/نقطه + Swipe روی موبایل.
(() => {
  const root = document.querySelector("[data-slider]");
  if (!root) return;
  const slides = [...root.querySelectorAll("[data-slide]")];
  if (slides.length < 2) return;

  const dots = [...root.querySelectorAll("[data-dot]")];
  let index = 0;
  let timer = null;
  let startX = 0;
  let startY = 0;
  let touching = false;

  const show = (next) => {
    index = (next + slides.length) % slides.length;
    slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
    dots.forEach((dot, i) => dot.classList.toggle("active", i === index));
  };

  const start = () => {
    clearInterval(timer);
    timer = setInterval(() => show(index + 1), 5000);
  };

  const manual = (next) => {
    show(next);
    start();
  };

  root.querySelector("[data-next]")?.addEventListener("click", () => manual(index + 1));
  root.querySelector("[data-prev]")?.addEventListener("click", () => manual(index - 1));
  dots.forEach((dot, i) => dot.addEventListener("click", () => manual(i)));

  root.addEventListener(
    "touchstart",
    (event) => {
      const touch = event.changedTouches[0];
      startX = touch.clientX;
      startY = touch.clientY;
      touching = true;
      clearInterval(timer);
    },
    { passive: true }
  );

  root.addEventListener(
    "touchend",
    (event) => {
      if (!touching) return;
      touching = false;
      const touch = event.changedTouches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (Math.abs(dx) >= 45 && Math.abs(dx) > Math.abs(dy) * 1.15) {
        // کشیدن به چپ = اسلاید بعدی، کشیدن به راست = قبلی.
        show(dx < 0 ? index + 1 : index - 1);
      }
      start();
    },
    { passive: true }
  );

  root.addEventListener("touchcancel", start, { passive: true });
  start();
})();
