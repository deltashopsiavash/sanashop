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

