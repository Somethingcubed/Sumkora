(() => {
  const isChinese = document.documentElement.lang === "zh";

  const typeset = async (element) => {
    if (!element) return;
    // Dynamic recovery can finish before the deferred MathJax bundle has
    // completed startup. Wait for it instead of silently leaving raw TeX on
    // the card forever.
    const deadline = Date.now() + 8000;
    while (!window.MathJax?.typesetPromise && Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
    if (!window.MathJax?.typesetPromise) return;
    try {
      if (window.MathJax.startup?.promise) {
        await window.MathJax.startup.promise;
      }
      window.MathJax.typesetClear?.([element]);
      await window.MathJax.typesetPromise([element]);
    } catch (_) {}
  };

  const cardFor = (details) => details.closest("[data-mistake-entry-id]");

  const applyResult = (details, result) => {
    const card = cardFor(details);
    const questionBody = card?.querySelector("[data-question-body]");
    const body = details.querySelector("[data-solution-body]");
    const loading = body?.querySelector(".mistake-solution-loading");

    if (result?.ok === false || !result?.question) {
      const retries = Number(details.dataset.retryCount || "0");
      if (questionBody) {
        questionBody.textContent = retries < 2
          ? (isChinese
              ? "正在自动重试恢复完整题目…"
              : "Automatically retrying the complete question…")
          : (isChinese
              ? "暂时无法生成文字版；上方原题图片仍可正常查看。展开解答即可重试。"
              : "The text version is temporarily unavailable; the original image above is still complete. Open the solution to retry.");
      }
      if (loading) {
        loading.textContent = retries < 2
          ? (isChinese ? "正在自动重试…" : "Retrying automatically…")
          : (isChinese ? "展开此处即可重试。" : "Open this section to retry.");
      }
      details.dataset.loaded = "false";
      return false;
    }

    if (questionBody) {
      questionBody.textContent = result.question;
      void typeset(questionBody);
    }
    if (body) {
      const solution = document.createElement("div");
      solution.className = "math-copy whitespace-pre-line";
      solution.textContent = result.solution || "";
      if (loading) loading.replaceWith(solution);
      else body.prepend(solution);
      void typeset(solution);
    }
    details.dataset.loaded = "true";
    details.dataset.needsQuestionRecovery = "false";
    details.dataset.retryCount = "0";
    return true;
  };

  const scheduleRetry = (details) => {
    const retries = Number(details.dataset.retryCount || "0");
    if (retries >= 2 || details.retryTimer) return;
    details.dataset.retryCount = String(retries + 1);
    details.retryTimer = window.setTimeout(() => {
      details.retryTimer = null;
      void loadOne(details);
    }, retries === 0 ? 1500 : 4000);
  };

  const loadOne = async (details) => {
    if (details.dataset.loaded === "true") return;
    if (details.contentPromise) return details.contentPromise;
    details.dataset.loaded = "loading";
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 29000);
    details.contentPromise = fetch(details.dataset.solutionUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("solution unavailable");
        const ok = applyResult(details, await response.json());
        if (!ok) scheduleRetry(details);
      })
      .catch(() => {
        applyResult(details, { ok: false });
        scheduleRetry(details);
      })
      .finally(() => {
        window.clearTimeout(timeout);
        details.contentPromise = null;
      });
    return details.contentPromise;
  };

  const allDetails = Array.from(
    document.querySelectorAll("[data-mistake-solution]")
  );

  allDetails.forEach((details) => {
    const state = details.querySelector(".disclosure-state");
    details.addEventListener("toggle", async () => {
      if (state) {
        state.textContent = details.open
          ? state.dataset.openLabel
          : state.dataset.closedLabel;
      }
      if (details.open && details.dataset.loaded !== "true") {
        await loadOne(details);
      }
    });
  });

  // Prepare exactly the first three incomplete cards in one browser request.
  // Everything else remains dormant until opened, even in a 130-item book.
  const firstThree = allDetails
    .filter((details) => details.dataset.needsQuestionRecovery === "true")
    .slice(0, 3);
  if (!firstThree.length) return;

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 29500);
  fetch("/student/mistakes/prefetch", {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) throw new Error("prefetch unavailable");
      const payload = await response.json();
      const byId = new Map(
        (payload.items || []).map((item) => [String(item.id), item])
      );
      firstThree.forEach((details) => {
        const ok = applyResult(
          details,
          byId.get(String(details.dataset.entryId)) || { ok: false }
        );
        if (!ok) scheduleRetry(details);
      });
    })
    .catch(() => {
      firstThree.forEach((details) => {
        applyResult(details, { ok: false });
        scheduleRetry(details);
      });
    })
    .finally(() => window.clearTimeout(timeout));
})();
