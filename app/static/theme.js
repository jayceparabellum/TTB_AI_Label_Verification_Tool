// Light/dark theme toggle. The initial theme is resolved before paint by the inline
// script in base.html (saved choice, else OS preference); this only handles the
// click + persistence. The app is fully usable with JS off (defaults to dark).
(function () {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  function current() {
    return document.documentElement.dataset.theme === "light" ? "light" : "dark";
  }
  btn.setAttribute("aria-pressed", String(current() === "dark"));
  btn.addEventListener("click", function () {
    var next = current() === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    btn.setAttribute("aria-pressed", String(next === "dark"));
    try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
  });
})();
