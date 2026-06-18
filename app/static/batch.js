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
