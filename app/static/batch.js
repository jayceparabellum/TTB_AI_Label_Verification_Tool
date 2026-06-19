// Filter the batch results table to only rows needing attention.
// Without JS the checkbox is inert and all rows show (progressive enhancement).
(function () {
  "use strict";
  var checkbox = document.getElementById("attnFilter");
  var table = document.getElementById("batchTable");
  if (!checkbox || !table) return;
  checkbox.addEventListener("change", function () {
    table.classList.toggle("attn-only", checkbox.checked);
  });
})();

// Batch form: "select a folder" enables webkitdirectory on the images input for one
// pick (folders submit through the same field; the server skips non-image junk and
// matches by basename), then drops the attribute so a later pick is normal file mode.
(function () {
  "use strict";
  var folderBtn = document.getElementById("pick-folder");
  var images = document.getElementById("batch-images");
  if (!folderBtn || !images) return;
  folderBtn.addEventListener("click", function () {
    images.setAttribute("webkitdirectory", "");
    images.click();
  });
  images.addEventListener("change", function () {
    images.removeAttribute("webkitdirectory");   // selected files remain; mode resets
  });
})();
