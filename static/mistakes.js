(() => {
  const typeset = (element) => {
    if (window.MathJax?.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {});
    }
  };

  document.querySelectorAll("[data-mistake-solution]").forEach((details) => {
    const state = details.querySelector(".disclosure-state");
    const body = details.querySelector("[data-solution-body]");
    details.addEventListener("toggle", async () => {
      if (state) {
        state.textContent = details.open
          ? state.dataset.openLabel
          : state.dataset.closedLabel;
      }
      if (!details.open || details.dataset.loaded === "true") return;
      details.dataset.loaded = "loading";
      try {
        const response = await fetch(details.dataset.solutionUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error("solution unavailable");
        const result = await response.json();
        const loading = body.querySelector(".mistake-solution-loading");
        const solution = document.createElement("div");
        solution.className = "math-copy whitespace-pre-line";
        solution.textContent = result.solution;
        if (loading) loading.replaceWith(solution);
        else body.prepend(solution);
        details.dataset.loaded = "true";
        typeset(solution);
      } catch (_) {
        const loading = body.querySelector(".mistake-solution-loading");
        if (loading) {
          loading.textContent = document.documentElement.lang === "zh"
            ? "暂时无法生成解答，请稍后重试。"
            : "The solution is temporarily unavailable. Please try again.";
        }
        details.dataset.loaded = "false";
      }
    });
  });
})();
