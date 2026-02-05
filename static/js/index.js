(function () {
  const fileInput = document.getElementById("file-input");
  const dropZone = document.getElementById("drop-zone");
  const fileList = document.getElementById("file-list");
  const fileCountPill = document.getElementById("file-count-pill");

  if (!fileInput || !dropZone || !fileList || !fileCountPill) return;

  function bytesToSize(bytes) {
    if (bytes === null || bytes === undefined) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let idx = 0;
    while (value >= 1024 && idx < units.length - 1) {
      value /= 1024;
      idx += 1;
    }
    const rounded = value < 10 && idx > 0 ? value.toFixed(1) : value.toFixed(0);
    return `${rounded} ${units[idx]}`;
  }

  function refreshFileList(files) {
    const entries = Array.from(files || []);
    if (!entries.length) {
      fileList.innerHTML = '<li class="empty-state">No files selected yet.</li>';
      fileCountPill.textContent = "0 files";
      return;
    }

    fileCountPill.textContent = entries.length === 1 ? "1 file" : `${entries.length} files`;
    fileList.innerHTML = entries
      .map((file) => {
        const safeName = String(file.name || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
        return (
          '<li class="file-item">' +
          `<span class="file-name" title="${safeName}">${safeName}</span>` +
          `<span class="file-size">${bytesToSize(file.size)}</span>` +
          "</li>"
        );
      })
      .join("");
  }

  function openPicker() {
    fileInput.click();
  }

  dropZone.addEventListener("click", (event) => {
    if (event.target.closest(".btn-primary")) return;
    event.preventDefault();
    openPicker();
  });

  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  });

  fileInput.addEventListener("change", (event) => {
    refreshFileList(event.target.files);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    const files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) return;

    const transfer = new DataTransfer();
    Array.from(files).forEach((file) => transfer.items.add(file));
    fileInput.files = transfer.files;
    refreshFileList(fileInput.files);
  });
})();
