(() => {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {});
    });
  }

  let installPrompt = null;
  const buttons = Array.from(document.querySelectorAll("[data-install-app]"));
  const help = document.querySelector("[data-install-help]");
  const helpCloseButtons = Array.from(document.querySelectorAll("[data-install-help-close]"));
  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

  const showInstallHelp = () => {
    if (!help) return;
    help.classList.remove("hidden");
    document.body.classList.add("install-help-open");
    const closeButton = help.querySelector("[data-install-help-close]");
    if (closeButton) closeButton.focus();
  };

  const hideInstallHelp = () => {
    if (!help) return;
    help.classList.add("hidden");
    document.body.classList.remove("install-help-open");
  };

  if (isStandalone) {
    buttons.forEach((button) => { button.hidden = true; });
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    buttons.forEach((button) => { button.hidden = false; });
  });
  buttons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (!installPrompt) {
        showInstallHelp();
        return;
      }
      installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      installPrompt = null;
      if (choice.outcome === "accepted") {
        buttons.forEach((item) => { item.hidden = true; });
      }
    });
  });
  helpCloseButtons.forEach((button) => button.addEventListener("click", hideInstallHelp));
  if (help) {
    help.addEventListener("click", (event) => {
      if (event.target === help) hideInstallHelp();
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideInstallHelp();
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    hideInstallHelp();
    buttons.forEach((button) => { button.hidden = true; });
  });
})();
