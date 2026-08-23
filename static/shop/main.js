document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try { await navigator.clipboard.writeText(button.dataset.copy); const old = button.textContent; button.textContent = "کپی شد ✓"; setTimeout(() => (button.textContent = old), 1800); } catch (_) {}
});

(() => {
  const root = document.querySelector("[data-slider]");
  if (!root) return;
  const slides = [...root.querySelectorAll("[data-slide]")];
  if (slides.length < 2) return;
  const dots = [...root.querySelectorAll("[data-dot]")];
  let index = 0, timer;
  const show = (next) => { index = (next + slides.length) % slides.length; slides.forEach((s,i)=>s.classList.toggle("is-active", i === index)); dots.forEach((d,i)=>d.classList.toggle("active", i === index)); };
  const start = () => { clearInterval(timer); timer = setInterval(()=>show(index+1), 5500); };
  root.querySelector("[data-next]")?.addEventListener("click", ()=>{show(index+1);start();});
  root.querySelector("[data-prev]")?.addEventListener("click", ()=>{show(index-1);start();});
  dots.forEach((dot,i)=>dot.addEventListener("click",()=>{show(i);start();}));
  start();
})();
