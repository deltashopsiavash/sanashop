/* Progressive enhancement: server validates option ID and always computes price. */
(() => {
  const group = document.querySelector('[data-numbered-options]');
  if (!group) return;
  const price = document.querySelector('[data-option-price]');
  const hint = document.querySelector('[data-option-price-hint]');
  const radios = Array.from(group.querySelectorAll('[data-option-radio]'));
  const formatter = new Intl.NumberFormat('fa-IR');
  group.addEventListener('change', (event) => {
    const choice = event.target;
    if (!choice.matches('[data-option-radio]') || choice.disabled) return;
    const amount = Number(choice.dataset.price);
    if (price && Number.isFinite(amount)) price.textContent = formatter.format(amount);
    if (hint) hint.textContent = 'قیمت انتخاب‌شده؛ کد ' + (choice.dataset.code || '');
  });
})();
