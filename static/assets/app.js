/* Guide Check — shared chrome: theme toggle, mobile nav, active link.
   No dependencies. Safe to load with `defer` on every page. */
(function () {
  "use strict";

  /* ---- theme: light / dark / system, persisted per browser --------------- */
  var KEY = "gc-theme";

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function store(v) {
    try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch (e) { /* private mode */ }
  }
  function apply(v) {
    if (v === "light" || v === "dark") document.documentElement.setAttribute("data-theme", v);
    else document.documentElement.removeAttribute("data-theme");
  }
  function current() {
    var s = stored();
    if (s === "light" || s === "dark") return s;
    return "system";
  }
  function effective() {
    var c = current();
    if (c !== "system") return c;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  apply(stored());

  function wireTheme() {
    var btn = document.getElementById("themeBtn");
    if (!btn) return;
    var sun = btn.querySelector('[data-icon="sun"]');
    var moon = btn.querySelector('[data-icon="moon"]');

    function paint() {
      var dark = effective() === "dark";
      if (sun) sun.style.display = dark ? "none" : "block";
      if (moon) moon.style.display = dark ? "block" : "none";
      btn.setAttribute("aria-label", "Switch to " + (dark ? "light" : "dark") + " theme");
      btn.setAttribute("title", "Theme: " + current());
    }
    btn.addEventListener("click", function () {
      var next = effective() === "dark" ? "light" : "dark";
      store(next); apply(next); paint();
    });
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () { if (current() === "system") paint(); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }
    paint();
  }

  /* ---- mobile nav -------------------------------------------------------- */
  function wireNav() {
    var btn = document.getElementById("navBtn");
    var nav = document.getElementById("nav");
    if (!btn || !nav) return;
    btn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") {
        nav.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("open")) {
        nav.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
        btn.focus();
      }
    });
  }

  /* ---- mark the current page in the nav ---------------------------------- */
  function wireCurrent() {
    var here = location.pathname.replace(/\/$/, "") || "/";
    if (here.length > 1 && here.slice(-5) === ".html") here = here.slice(0, -5);
    var links = document.querySelectorAll("#nav a");
    for (var i = 0; i < links.length; i++) {
      var p = links[i].getAttribute("href") || "";
      p = p.replace(/\/$/, "") || "/";
      if (p.length > 1 && p.slice(-5) === ".html") p = p.slice(0, -5);
      if (p === here) links[i].setAttribute("aria-current", "page");
    }
  }

  function boot() { wireTheme(); wireNav(); wireCurrent(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
