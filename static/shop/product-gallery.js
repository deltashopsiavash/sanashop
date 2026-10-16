/* No dependencies: switch a product's main photo using the image thumbnails. */
(() => {
  for (const gallery of document.querySelectorAll("[data-product-gallery]")) {
    const main = gallery.querySelector("[data-gallery-main]");
    const thumbs = [...gallery.querySelectorAll("[data-gallery-thumb]")];
    if (!main || !thumbs.length) continue;
    const previous = gallery.querySelector("[data-gallery-prev]");
    const next = gallery.querySelector("[data-gallery-next]");
    let current = Math.max(0, thumbs.findIndex(button => button.classList.contains("is-active")));
    function show(index) {
      current = (index + thumbs.length) % thumbs.length;
      const selected = thumbs[current];
      main.src = selected.dataset.gallerySrc;
      main.alt = selected.dataset.galleryAlt || "";
      thumbs.forEach((thumb, i) => {
        const active = i === current;
        thumb.classList.toggle("is-active", active);
        thumb.setAttribute("aria-pressed", String(active));
      });
      selected.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    }
    thumbs.forEach((button, index) => button.addEventListener("click", () => show(index)));
    if (previous) {
      previous.disabled = thumbs.length < 2;
      previous.addEventListener("click", () => show(current - 1));
    }
    if (next) {
      next.disabled = thumbs.length < 2;
      next.addEventListener("click", () => show(current + 1));
    }
    gallery.addEventListener("keydown", event => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (!gallery.contains(document.activeElement)) return;
      event.preventDefault();
      show(current + (event.key === "ArrowLeft" ? 1 : -1));
      thumbs[current].focus();
    });
  }
})();
