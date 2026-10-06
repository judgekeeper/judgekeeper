/*
  The theme, set before the page is drawn, so it never flashes. Loaded in <head> without
  defer. Dark by default; light when the system asks for it (style.css). A choice made with
  the switch in the header is kept in this browser only and wins over both.
*/
(function () {
  "use strict";
  var root = document.documentElement, saved = null;
  root.classList.add("js");
  try { saved = window.localStorage.getItem("jk-theme"); } catch (e) { saved = null; }
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
})();
