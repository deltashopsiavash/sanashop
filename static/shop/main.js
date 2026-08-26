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

// حساب کاربری: نمایش ورود/عضویت به شکل پنجره شناور با پس‌زمینه تار.
(() => {
  const dialog = document.getElementById("accountDialog");
  if (!dialog || typeof dialog.showModal !== "function") return;

  const openDialog = () => {
    if (!dialog.open) dialog.showModal();
    window.setTimeout(() => dialog.querySelector('input[name="email"]')?.focus(), 60);
  };
  const closeDialog = () => {
    if (dialog.open) dialog.close();
  };

  document.querySelectorAll("[data-account-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      document.body.classList.remove("menu-open", "search-open");
      openDialog();
    });
  });
  dialog.querySelector("[data-account-close]")?.addEventListener("click", closeDialog);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialog();
  });
})();

// تمام فیلدهای رمز عبور در ورود، ثبت‌نام و بازیابی رمز دکمه چشم دارند.
(() => {
  const eyeOpen = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.8"/></svg>';
  const eyeClosed = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.7 6.1A10.5 10.5 0 0 1 12 6c6 0 9.5 6 9.5 6a16.7 16.7 0 0 1-2.1 2.8M6.2 6.2C3.8 8 2.5 12 2.5 12s3.5 6 9.5 6c1.4 0 2.6-.3 3.7-.8M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  document.querySelectorAll('input[type="password"]').forEach((input) => {
    if (input.closest(".password-field-wrap")) return;
    const wrap = document.createElement("div");
    wrap.className = "password-field-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.setAttribute("aria-label", "نمایش رمز عبور");
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = eyeOpen;
    button.addEventListener("click", () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.setAttribute("aria-label", show ? "مخفی کردن رمز عبور" : "نمایش رمز عبور");
      button.innerHTML = show ? eyeClosed : eyeOpen;
      input.focus({ preventScroll: true });
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (_) {}
    });
    wrap.appendChild(button);
  });
})();

// کد OTP را با اعداد فارسی/عربی هم می‌پذیریم و فقط شش رقم نگه می‌داریم.
(() => {
  const input = document.querySelector(".otp-input");
  if (!input) return;
  const normalize = (value) => value
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/\D/g, "")
    .slice(0, 6);
  input.addEventListener("input", () => { input.value = normalize(input.value); });
  input.addEventListener("paste", () => window.setTimeout(() => { input.value = normalize(input.value); }, 0));
})();
