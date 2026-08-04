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
    const cameraInput = uploader.querySelector("[data-camera-input]");
    const form = input.closest("form");
    const preview = uploader.querySelector("[data-page-preview]");
    const status = uploader.querySelector("[data-file-status]");
    const error = uploader.querySelector("[data-upload-error]");
    const submit = form.querySelector("[data-submit-button]");
    const progress = form.querySelector("[data-upload-progress]");
    const progressLabel = form.querySelector("[data-upload-progress-label]");
    const progressValue = form.querySelector("[data-upload-progress-value]");
    const progressFill = form.querySelector("[data-upload-progress-fill]");
    const retry = form.querySelector("[data-upload-retry]");
    const maximumPages = Number(uploader.dataset.maxPages || 30);
    const maximumBytes = Number(uploader.dataset.maxBytes || 26214400);
    let pages = [];
    let preparedFiles = null;

    const clearError = () => {
      error.hidden = true;
      error.textContent = "";
    };

    const showError = (message) => {
      error.textContent = message;
      error.hidden = false;
    };

    const setProgress = (percent, label) => {
      const value = Math.max(0, Math.min(100, Math.round(percent)));
      progress.hidden = false;
      progressFill.style.width = `${value}%`;
      progressValue.textContent = `${value}%`;
      if (label) progressLabel.textContent = label;
    };

    const resetPrepared = () => {
      preparedFiles = null;
      retry.hidden = true;
    };

    const disposePages = () => {
      pages.forEach((page) => {
        if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
      });
      pages = [];
      resetPrepared();
    };

    const syncInput = (files = pages.map((page) => page.file)) => {
      const transfer = new DataTransfer();
      files.forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
    };

    const inspectImage = async (page) => {
      try {
        const image = await loadImage(page.file);
        page.warning = Math.min(image.naturalWidth, image.naturalHeight) < 900;
      } catch (_) {
        page.warning = true;
      }
      render();
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

    const replacePage = (page) => {
      const replacement = document.createElement("input");
      replacement.type = "file";
      replacement.accept = "image/jpeg,image/png,image/webp";
      replacement.hidden = true;
      replacement.addEventListener("change", () => {
        const file = replacement.files && replacement.files[0];
        if (!file || !supportedImage(file)) return;
        if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
        page.file = file;
        page.rotation = 0;
        page.warning = false;
        page.previewUrl = URL.createObjectURL(file);
        resetPrepared();
        render();
        inspectImage(page);
      });
      document.body.append(replacement);
      replacement.click();
      window.setTimeout(() => replacement.remove(), 60000);
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
              resetPrepared();
              render();
            }, index === 0),
            control(uploader.dataset.moveLater, "→", () => {
              [pages[index], pages[index + 1]] = [pages[index + 1], pages[index]];
              resetPrepared();
              render();
            }, index === pages.length - 1),
            control(uploader.dataset.rotate, "↻", () => {
              page.rotation = (page.rotation + 90) % 360;
              resetPrepared();
              render();
            }),
            control(uploader.dataset.replace, "⇄", () => replacePage(page)),
          );
        }
        controls.append(
          control(uploader.dataset.remove, "×", () => {
            if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
            pages.splice(index, 1);
            resetPrepared();
            render();
          }),
        );
        card.append(visual, label);
        if (page.warning) {
          const warning = document.createElement("p");
          warning.className = "multi-page-warning";
          warning.textContent = uploader.dataset.imageWarning;
          card.append(warning);
        }
        card.append(controls);
        preview.append(card);
      });
      syncInput();
    };

    const addSelected = (selected) => {
      clearError();
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
          const page = {
            file,
            kind: "image",
            rotation: 0,
            warning: false,
            previewUrl: URL.createObjectURL(file),
          };
          pages.push(page);
          known.add(key);
          inspectImage(page);
        }
      });
      if (pages.length > maximumPages) {
        pages.splice(maximumPages).forEach((page) => {
          if (page.previewUrl) URL.revokeObjectURL(page.previewUrl);
        });
        showError(uploader.dataset.tooMany);
      }
      resetPrepared();
      render();
    };

    input.addEventListener("change", () => addSelected(Array.from(input.files)));
    if (cameraInput) {
      cameraInput.addEventListener("change", () => {
        addSelected(Array.from(cameraInput.files || []));
        cameraInput.value = "";
      });
    }

    const sendUpload = () => {
      clearError();
      retry.hidden = true;
      if (preparedFiles) syncInput(preparedFiles);
      const request = new XMLHttpRequest();
      request.open("POST", form.action);
      request.timeout = 120000;
      request.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        setProgress(30 + (event.loaded / event.total) * 70, uploader.dataset.uploading);
      });
      request.addEventListener("load", () => {
        if (request.status >= 200 && request.status < 400 && request.responseURL) {
          setProgress(100, uploader.dataset.uploading);
          window.location.assign(request.responseURL);
          return;
        }
        const responseDocument = new DOMParser().parseFromString(
          request.responseText || "",
          "text/html",
        );
        const serverMessage = responseDocument.querySelector('[role="alert"]')?.textContent?.trim();
        showError(serverMessage || uploader.dataset.uploadFailed);
        retry.hidden = false;
        submit.disabled = false;
        form.removeAttribute("aria-busy");
      });
      const interrupted = () => {
        showError(uploader.dataset.uploadFailed);
        retry.hidden = false;
        submit.disabled = false;
        form.removeAttribute("aria-busy");
      };
      request.addEventListener("error", interrupted);
      request.addEventListener("timeout", interrupted);
      request.send(new FormData(form));
    };

    retry.addEventListener("click", sendUpload);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity() || !pages.length) return;
      clearError();
      submit.disabled = true;
      form.setAttribute("aria-busy", "true");
      try {
        if (pages[0].kind === "pdf") {
          preparedFiles = pages.map((page) => page.file);
          setProgress(30, uploader.dataset.uploading);
          sendUpload();
          return;
        }
        const prepared = [];
        for (let index = 0; index < pages.length; index += 1) {
          const label = `${uploader.dataset.preparing} ${index + 1} ${uploader.dataset.preparingSuffix} ${pages.length}`;
          status.textContent = label;
          setProgress(((index + 1) / pages.length) * 28, label);
          prepared.push(await prepareImage(pages[index].file, pages[index].rotation, index + 1));
        }
        const totalSize = prepared.reduce((sum, file) => sum + file.size, 0);
        if (totalSize > maximumBytes) throw new Error(uploader.dataset.tooLarge);
        preparedFiles = prepared;
        sendUpload();
      } catch (caught) {
        showError(
          caught.message === uploader.dataset.tooLarge
            ? uploader.dataset.tooLarge
            : uploader.dataset.prepareError,
        );
        status.textContent = `${pages.length} ${uploader.dataset.pages}`;
        submit.disabled = false;
        form.removeAttribute("aria-busy");
      }
    });

    render();
  });
})();
