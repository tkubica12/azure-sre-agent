// Head-loaded theme bootstrap: sets data-theme on <html> synchronously,
// before CSS/first paint, so a persisted or system-preferred dark theme
// never flashes light first. This is intentionally a separate, tiny file
// from theme.js (which still owns the toggle button wiring and persistence
// and runs at the normal end-of-body position) - loading the FULL theme.js
// this early would run its DOMContentLoaded-deferred button wiring against
// a document that does not have those buttons yet.
//
// Must be loaded with a plain <script src> as the FIRST element in <head>,
// before the stylesheet <link> tags, so it runs (script fetch/execute is
// render-blocking) before any CSS is applied. Uses the same storage key as
// theme.js; keep both in sync if the key ever changes.
(function () {
  "use strict";
  try {
    var stored = window.localStorage.getItem("sre-agent-demo-theme");
    var theme =
      stored === "dark" || stored === "light"
        ? stored
        : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (err) {
    // localStorage can throw under restricted file:// contexts; the
    // static data-theme="light" attribute already on <html> is the fallback.
  }
})();
