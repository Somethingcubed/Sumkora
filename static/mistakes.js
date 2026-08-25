(() => {
  const isChinese = document.documentElement.lang === "zh";

  const typeset = (element) => {
    if (element && window.MathJax?.typesetPromise) {
      window.MathJax.typesetPromise([element]).catch(() => {});
    }
  };

  const cardFor = (details) => details.closest("[data-mistake-entry-id]");

  const applyResult = (details, result) => {
    const card = cardFor(details);
    const questionBody = card?.querySelector("[data-question-body]");
    const body = details.querySelector("[data-solution-body]");
    const loading = body?.querySelector(".mistake-solution-loading");

    if (result?.ok === false || !result?.question) {
      if (questionBody) {
        questionBody.textContent = isChinese
          ? "暂时无法恢复完整题目。展开解答即可重试。"
          : "The complete question is not ready yet. Open the solution to retry.";
      }
      if (loading) {
        loading.textContent = isChinese
          ? "展开此处即可重试。"
          : "Open this section to retry.";
      }
      details.dataset.loaded = "false";
      return;
    }

    if (questionBody) {
      questionBody.textContent = result.question;
      typeset(questionBody);
    }
    if (body) {
      const solution = document.createElement("div");
      solution.className = "math-copy whitespace-pre-line";
      solution.textContent = result.solution || "";
      if (loading) loading.replaceWith(solution);
      else body.prepend(solution);
      typeset(solution);
    }
    details.dataset.loaded = "true";
    details.dataset.needsQuestionRecovery = "false";
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
        applyResult(details, await response.json());
      })
      .catch(() => applyResult(details, { ok: false }))
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
        applyResult(details, byId.get(String(details.dataset.entryId)) || { ok: false });
      });
    })
    .catch(() => {
      firstThree.forEach((details) => applyResult(details, { ok: false }));
    })
    .finally(() => window.clearTimeout(timeout));
})();
