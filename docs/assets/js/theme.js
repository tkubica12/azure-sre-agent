// Shared light/dark theme toggle for the slide deck and the presenter guide.
//
// Persists the presenter's manual choice in localStorage under
// "sre-agent-demo-theme" so the toggle survives reloads and navigation
// between the deck and the guide (both same-origin file:// or http:// paths
// share storage). Falls back to the operating system's prefers-color-scheme
// on first visit, before any manual choice has been made.
(function () {
  "use strict";

  var STORAGE_KEY = "sre-agent-demo-theme";
  var root = document.documentElement;

  function systemPrefersDark() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function readStoredTheme() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      // Storage can be unavailable (privacy mode, file:// restrictions in
      // some browsers). Theme toggling still works for the session; it
      // simply will not persist.
      return null;
    }
  }

  function writeStoredTheme(value) {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch (err) {
      /* ignore */
    }
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      var isDark = theme === "dark";
      btn.setAttribute("aria-pressed", String(isDark));
      var label = btn.querySelector("[data-theme-toggle-label]");
      if (label) {
        label.textContent = isDark ? "Light mode" : "Dark mode";
      }
    });
  }

  function currentTheme() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function initTheme() {
    var stored = readStoredTheme();
    var theme = stored === "dark" || stored === "light"
      ? stored
      : systemPrefersDark()
        ? "dark"
        : "light";
    apply(theme);
  }

  function toggleTheme() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    apply(next);
    writeStoredTheme(next);
  }

  // Apply as early as possible to avoid a flash of the wrong theme.
  initTheme();

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.addEventListener("click", toggleTheme);
    });
    // Re-apply so newly rendered toggle buttons reflect current state.
    apply(currentTheme());
  });

  window.SreAgentDemoTheme = {
    toggle: toggleTheme,
    current: currentTheme,
  };
})();
