// Progressive enhancement for the upload field: drag-and-drop + thumbnail
// preview. Without this script the plain <input type=file> still works.
(function () {
  "use strict";
  var dropzone = document.getElementById("dropzone");
  var input = document.getElementById("fileInput");
  var preview = document.getElementById("preview");
  if (!dropzone || !input || !preview) return;

  function showPreview(file) {
    if (!file || !file.type || file.type.indexOf("image/") !== 0) {
      preview.hidden = true;
      return;
    }
    if (preview.src) URL.revokeObjectURL(preview.src);
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
    dropzone.classList.add("has-file");
  }

  input.addEventListener("change", function () {
    showPreview(input.files && input.files[0]);
  });

  ["dragenter", "dragover"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragging");
    });
  });

  dropzone.addEventListener("drop", function (e) {
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) {
      input.files = files; // populate the real input so the form submits it
      showPreview(files[0]);
    }
  });
})();
