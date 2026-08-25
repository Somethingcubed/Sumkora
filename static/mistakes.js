(() => {
  let recoveryQueue = Promise.resolve();

  const enqueueRecovery = (task) => {
    const pending = recoveryQueue.then(task, task);
    recoveryQueue = pending.catch(() => {});
    return pending;
  };

  const typeset = (element) => {
    if (window.MathJax?.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {});
    }
  };

  document.querySelectorAll("[data-mistake-solution]").forEach((details) => {
    const state = details.querySelector(".disclosure-state");
    const body = details.querySelector("[data-solution-body]");
    let contentPromise = null;
    const loadContent = async () => {
      if (details.dataset.loaded === "true") return;
      if (contentPromise) return contentPromise;
      details.dataset.loaded = "loading";
      contentPromise = enqueueRecovery(async () => {
        try {
          const response = await fetch(details.dataset.solutionUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
          });
          if (!response.ok) throw new Error("solution unavailable");
          const result = await response.json();
          const questionBody = details.closest("section")
            ?.querySelector("[data-question-body]");
          if (questionBody && result.question) {
            questionBody.textContent = result.question;
            typeset(questionBody);
          }
          const loading = body.querySelector(".mistake-solution-loading");
          const solution = document.createElement("div");
          solution.className = "math-copy whitespace-pre-line";
          solution.textContent = result.solution;
          if (loading) loading.replaceWith(solution);
          else body.prepend(solution);
          details.dataset.loaded = "true";
          details.dataset.needsQuestionRecovery = "false";
          typeset(solution);
        } catch (_) {
          const questionBody = details.closest("section")
            ?.querySelector("[data-question-body]");
          if (questionBody && details.dataset.needsQuestionRecovery === "true") {
            questionBody.textContent = document.documentElement.lang === "zh"
              ? "暂时无法恢复完整题目，请稍后重试。"
              : "The complete question is temporarily unavailable. Please try again.";
          }
          const loading = body.querySelector(".mistake-solution-loading");
          if (loading) {
            loading.textContent = document.documentElement.lang === "zh"
              ? "暂时无法生成解答，请稍后重试。"
              : "The solution is temporarily unavailable. Please try again.";
          }
          details.dataset.loaded = "false";
          contentPromise = null;
        }
      });
      return contentPromise;
    };

    details.addEventListener("toggle", async () => {
      if (state) {
        state.textContent = details.open
          ? state.dataset.openLabel
          : state.dataset.closedLabel;
      }
      if (!details.open) return;
      await loadContent();
    });

    if (details.dataset.needsQuestionRecovery === "true") {
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          loadContent();
        }
      }, { rootMargin: "0px" });
      observer.observe(details.closest("section") || details);
    }
  });
})();
