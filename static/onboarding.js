(() => {
  const tour = document.querySelector("[data-onboarding-tour]");
  if (tour) {
    const viewport = tour.querySelector("[data-tour-viewport]");
    const slides = [...tour.querySelectorAll(".tour-slide")];
    const dots = [...tour.querySelectorAll("[data-tour-dot]")];
    let active = 0;

    const show = (index) => {
      active = Math.max(0, Math.min(slides.length - 1, index));
      slides[active].scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "start",
      });
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle("active", dotIndex === active);
        dot.setAttribute("aria-current", dotIndex === active ? "true" : "false");
      });
    };

    tour.querySelector("[data-tour-prev]").addEventListener("click", () => show(active - 1));
    tour.querySelector("[data-tour-next]").addEventListener("click", () => show(active + 1));
    dots.forEach((dot, index) => dot.addEventListener("click", () => show(index)));
    viewport.addEventListener("scroll", () => {
      const index = Math.round(viewport.scrollLeft / Math.max(viewport.clientWidth, 1));
      if (index !== active && index >= 0 && index < slides.length) {
        active = index;
        dots.forEach((dot, dotIndex) => {
          dot.classList.toggle("active", dotIndex === active);
          dot.setAttribute("aria-current", dotIndex === active ? "true" : "false");
        });
      }
    }, { passive: true });
    viewport.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") show(active - 1);
      if (event.key === "ArrowRight") show(active + 1);
    });
  }

  const remember = document.querySelector("[data-remember-device]");
  const rememberStatus = document.querySelector("[data-remember-status]");
  if (remember) {
    remember.addEventListener("change", async () => {
      const body = new FormData();
      if (remember.checked) body.set("remember", "on");
      remember.disabled = true;
      try {
        const response = await fetch("/account/session-preference", {
          method: "POST",
          body,
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error("request failed");
        rememberStatus.textContent = remember.checked ? remember.dataset.onLabel : remember.dataset.offLabel;
      } catch (_error) {
        remember.checked = !remember.checked;
        rememberStatus.textContent = remember.dataset.errorLabel;
      } finally {
        remember.disabled = false;
      }
    });
  }
})();
