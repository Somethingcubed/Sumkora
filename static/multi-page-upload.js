(() => {
  const supportedImage = (file) =>
    ["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
    /\.(?:jpe?g|png|webp)$/i.test(file.name);
  const isPdf = (file) =>
    file.type === "application/pdf" || /\.pdf$/i.test(file.name);

  const loadImage = (file) =>
    new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        URL.revokeObjectURL(url);
        resolve(image);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("Unreadable image"));
      };
      image.src = url;
    });

  const canvasBlob = (canvas) =>
    new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("Image conversion failed"))),
        "image/jpeg",
        0.86,
      );
    });

  const prepareImage = async (file, rotation, pageNumber) => {
    const image = await loadImage(file);
    const scale = Math.min(1, 2400 / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    const quarterTurn = rotation % 180 !== 0;
    const canvas = document.createElement("canvas");
    canvas.width = quarterTurn ? height : width;
    canvas.height = quarterTurn ? width : height;
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.translate(canvas.width / 2, canvas.height / 2);
    context.rotate((rotation * Math.PI) / 180);
    context.drawImage(image, -width / 2, -height / 2, width, height);
    const blob = await canvasBlob(canvas);
    return new File(
      [blob],
      `page-${String(pageNumber).padStart(2, "0")}.jpg`,
      { type: "image/jpeg", lastModified: Date.now() },
    );
  };

  document.querySelectorAll("[data-file-input]").forEach((input) => {
    input.addEventListener("change", () => {
      const status = input.parentElement.querySelector("[data-file-status]");
      if (!status) return;
      status.textContent = input.files.length
        ? input.files[0].name
        : status.dataset.empty || "No file selected";
      status.classList.toggle("text-emerald-700", input.files.length > 0);
    });
  });

  document.querySelectorAll("[data-multi-page-uploader]").forEach((uploader) => {
    const input = uploader.querySelector("[data-multi-page-input]");
    const form = input.closest("form");
    const preview = uploader.querySelector("[data-page-preview]");
    const status = uploader.querySelector("[data-file-status]");
    const error = uploader.querySelector("[data-upload-error]");
    const submit = form.querySelector("[data-submit-button]");
    const maximumPages = Number(uploader.dataset.maxPages || 30);
    const maximumBytes = Number(uploader.dataset.maxBytes || 26214400);
    let pages = [];
    let preparedForSubmit = false;

    const clearError = () => {
      error.hidden = true;
      error.textContent = "";
    };

    const showError = (message) => {
      error.textContent = message;
      error.hidden = false;
    };

    const disposePages = () => {
      pages.forEach((page) => {
        if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
      });
      pages = [];
    };

    const syncInput = (files = pages.map((page) => page.file)) => {
      const transfer = new DataTransfer();
      files.forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
    };

    const control = (label, text, action, disabled = false) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "multi-page-control";
      button.setAttribute("aria-label", label);
      button.title = label;
      button.textContent = text;
      button.disabled = disabled;
      button.addEventListener("click", action);
      return button;
    };

    const render = () => {
      preview.replaceChildren();
      preview.hidden = pages.length === 0;
      status.classList.toggle("text-emerald-700", pages.length > 0);
      if (!pages.length) {
        status.textContent = uploader.dataset.empty;
        syncInput([]);
        return;
      }
      status.textContent = pages[0].kind === "pdf"
        ? uploader.dataset.onePdf
        : `${pages.length} ${uploader.dataset.pages}`;

      pages.forEach((page, index) => {
        const card = document.createElement("article");
        card.className = "multi-page-card";
        const visual = document.createElement("div");
        visual.className = "multi-page-visual";
        if (page.kind === "image") {
          const image = document.createElement("img");
          image.src = page.previewUrl;
          image.alt = `Page ${index + 1}`;
          image.style.transform = `rotate(${page.rotation}deg)`;
          visual.append(image);
        } else {
          visual.classList.add("multi-page-pdf");
          visual.textContent = "PDF";
        }
        const label = document.createElement("p");
        label.className = "multi-page-label";
        label.textContent = page.kind === "pdf" ? page.file.name : `Page ${index + 1}`;
        const controls = document.createElement("div");
        controls.className = "multi-page-controls";
        if (page.kind === "image") {
          controls.append(
            control(uploader.dataset.moveEarlier, "←", () => {
              [pages[index - 1], pages[index]] = [pages[index], pages[index - 1]];
              render();
            }, index === 0),
            control(uploader.dataset.moveLater, "→", () => {
              [pages[index], pages[index + 1]] = [pages[index + 1], pages[index]];
              render();
            }, index === pages.length - 1),
            control(uploader.dataset.rotate, "↻", () => {
              page.rotation = (page.rotation + 90) % 360;
              render();
            }),
          );
        }
        controls.append(
          control(uploader.dataset.remove, "×", () => {
            if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
            pages.splice(index, 1);
            render();
          }),
        );
        card.append(visual, label, controls);
        preview.append(card);
      });
      syncInput();
    };

    input.addEventListener("change", () => {
      clearError();
      const selected = Array.from(input.files);
      if (!selected.length) return;
      const pdfs = selected.filter(isPdf);
      if (pdfs.length) {
        if (selected.length !== 1) {
          showError(uploader.dataset.mixed);
          render();
          return;
        }
        disposePages();
        pages = [{ file: pdfs[0], kind: "pdf", rotation: 0 }];
        render();
        return;
      }
      if (selected.some((file) => !supportedImage(file))) {
        showError(uploader.dataset.unsupported);
        render();
        return;
      }
      if (pages[0]?.kind === "pdf") disposePages();
      const known = new Set(
        pages.map((page) => `${page.file.name}:${page.file.size}:${page.file.lastModified}`),
      );
      selected.forEach((file) => {
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (!known.has(key)) {
          pages.push({
            file,
            kind: "image",
            rotation: 0,
            previewUrl: URL.createObjectURL(file),
          });
          known.add(key);
        }
      });
      if (pages.length > maximumPages) {
        pages.splice(maximumPages).forEach((page) => {
          if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
        });
        showError(uploader.dataset.tooMany);
      }
      render();
    });

    form.addEventListener("submit", async (event) => {
      if (preparedForSubmit || pages[0]?.kind === "pdf" || !pages.length) {
        if (!form.checkValidity()) return;
        if (submit) submit.disabled = true;
        form.setAttribute("aria-busy", "true");
        return;
      }
      event.preventDefault();
      clearError();
      if (submit) submit.disabled = true;
      form.setAttribute("aria-busy", "true");
      try {
        const prepared = [];
        for (let index = 0; index < pages.length; index += 1) {
          status.textContent =
            `${uploader.dataset.preparing} ${index + 1} ` +
            `${uploader.dataset.preparingSuffix} ${pages.length}`;
          prepared.push(
            await prepareImage(
              pages[index].file,
              pages[index].rotation,
              index + 1,
            ),
          );
        }
        const totalSize = prepared.reduce((sum, file) => sum + file.size, 0);
        if (totalSize > maximumBytes) {
          throw new Error(uploader.dataset.tooLarge);
        }
        syncInput(prepared);
        preparedForSubmit = true;
        form.requestSubmit();
      } catch (caught) {
        showError(
          caught.message === uploader.dataset.tooLarge
            ? uploader.dataset.tooLarge
            : uploader.dataset.prepareError,
        );
        status.textContent = `${pages.length} ${uploader.dataset.pages}`;
        if (submit) submit.disabled = false;
        form.removeAttribute("aria-busy");
      }
    });

    render();
  });
})();
