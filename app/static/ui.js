// Global UI behaviors that must work under a strict Content-Security-Policy
// (no inline event handlers). Loaded on every page. No build step.
(function () {
  // Print / Save button on the results page (replaces an inline onclick so the CSP
  // can keep script-src 'self' with no 'unsafe-inline').
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-print]");
    if (btn) window.print();
  });
})();
