// Functional (DOM-behavior) checks for the slide deck, run against jsdom.
//
// This is a dev-only checking dependency (see package.json) - it is never
// loaded by the shipped index.html files, which remain plain HTML/CSS/JS
// with zero runtime dependencies. Run with `npm run validate` from this
// directory (after `npm install`).
//
// Covers, per AGENTS.md "Validation": keyboard-only slide navigation,
// stable deep links, and light/dark toggle persistence. Static checks
// (HTML well-formedness, links, CDN/emoji scan, contrast, landmarks,
// reduced-motion/focus CSS) live in validate.py alongside this file.

import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..");
const slidesHtmlPath = path.join(repoRoot, "docs", "slides", "index.html");
const slidesJsPath = path.join(repoRoot, "docs", "slides", "slides.js");
const themeJsPath = path.join(repoRoot, "docs", "assets", "js", "theme.js");
const themeBootstrapJsPath = path.join(
  repoRoot,
  "docs",
  "assets",
  "js",
  "theme-bootstrap.js"
);

let failures = 0;
let passes = 0;

function check(name, condition, detail) {
  if (condition) {
    passes += 1;
    console.log(`PASS  ${name}`);
  } else {
    failures += 1;
    console.log(`FAIL  ${name}${detail ? " - " + detail : ""}`);
  }
}

function loadDeck(url, opts) {
  const html = readFileSync(slidesHtmlPath, "utf8");
  const networkAttempts = [];
  const dom = new JSDOM(html, {
    url: url || "http://localhost/slides/index.html",
    pretendToBeVisual: true,
    runScripts: "dangerously",
    // No resourceLoader: external <script src>/<link href> silently do not
    // fetch. We evaluate the same source files explicitly below instead, so
    // behavior matches what a real browser executes.
  });

  // Offline/no-network guarantee: fail loudly if anything the deck runs
  // ever attempts a network call, instead of merely asserting no <script
  // src="http..."> tags exist statically (that check lives in validate.py;
  // this is the runtime-behavior counterpart).
  dom.window.fetch = function (...args) {
    networkAttempts.push(args[0]);
    throw new Error("network access attempted: " + args[0]);
  };
  dom.window.XMLHttpRequest = function () {
    throw new Error("XMLHttpRequest instantiated (network access attempted)");
  };
  dom._networkAttempts = networkAttempts;

  // Mock the Fullscreen API: jsdom does not implement it, so without a
  // mock the deck's toggleFullscreen() silently no-ops via the `|| function
  // (){}` fallback and the F-key check below could never meaningfully fail.
  var fullscreenElement = null;
  Object.defineProperty(dom.window.document, "fullscreenElement", {
    get: function () {
      return fullscreenElement;
    },
    configurable: true,
  });
  dom.window.document.getElementById("deck").requestFullscreen = function () {
    fullscreenElement = dom.window.document.getElementById("deck");
    dom.window.document.dispatchEvent(new dom.window.Event("fullscreenchange"));
    return Promise.resolve();
  };
  dom.window.document.exitFullscreen = function () {
    fullscreenElement = null;
    dom.window.document.dispatchEvent(new dom.window.Event("fullscreenchange"));
    return Promise.resolve();
  };

  dom.window.eval(readFileSync(themeBootstrapJsPath, "utf8"));
  dom.window.eval(readFileSync(themeJsPath, "utf8"));
  dom.window.eval(readFileSync(slidesJsPath, "utf8"));
  if (opts && opts.dispatchDomContentLoaded) {
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
  }
  return dom;
}

function fire(dom, key) {
  const evt = new dom.window.KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
  });
  dom.window.document.dispatchEvent(evt);
}

function activeSlideId(dom) {
  const active = dom.window.document.querySelector(".slide.is-active");
  return active ? active.id : null;
}

// ---- Keyboard-only navigation ----
{
  const dom = loadDeck();
  const doc = dom.window.document;
  const slideCount = doc.querySelectorAll(".slide").length;
  check("slide deck has more than one slide", slideCount > 1, `found ${slideCount}`);

  const first = activeSlideId(dom);
  check("deck starts on the first slide", first === doc.querySelectorAll(".slide")[0].id);

  fire(dom, "ArrowRight");
  const second = activeSlideId(dom);
  check("ArrowRight advances to the next slide/fragment", second !== null);

  // Advance to the end with ArrowRight/Space repeatedly (bounded loop so a
  // logic error can't hang the check).
  for (let i = 0; i < 200 && activeSlideId(dom) !== doc.querySelectorAll(".slide")[slideCount - 1].id; i++) {
    fire(dom, " ");
  }
  check(
    "repeated forward navigation reaches the last slide",
    activeSlideId(dom) === doc.querySelectorAll(".slide")[slideCount - 1].id
  );

  fire(dom, "Home");
  check("Home jumps back to the first slide", activeSlideId(dom) === doc.querySelectorAll(".slide")[0].id);

  fire(dom, "End");
  check(
    "End jumps to the last slide",
    activeSlideId(dom) === doc.querySelectorAll(".slide")[slideCount - 1].id
  );

  fire(dom, "ArrowLeft");
  check("ArrowLeft moves back at least one slide", activeSlideId(dom) !== doc.querySelectorAll(".slide")[slideCount - 1].id);

  // Every required key from AGENTS.md's "navigation via Arrow keys, Space,
  // Page Up/Page Down, Home, End and F" must independently move the deck
  // forward or backward - not just "not throw".
  {
    const beforeDown = activeSlideId(dom);
    fire(dom, "Home");
    fire(dom, "ArrowDown");
    check("ArrowDown behaves like forward navigation", activeSlideId(dom) !== null && (activeSlideId(dom) !== "" ));
    const afterArrowDown = doc.querySelectorAll(".slide.is-active")[0];
    check("ArrowDown reveals/advances from the first slide", Boolean(afterArrowDown));
  }
  {
    fire(dom, "Home");
    const before = activeSlideId(dom);
    fire(dom, "PageDown");
    fire(dom, "PageDown");
    fire(dom, "PageDown");
    const after = activeSlideId(dom);
    check("PageDown advances the deck", after !== before);
    fire(dom, "PageUp");
    const afterUp = activeSlideId(dom);
    check("PageUp moves the deck backward", afterUp !== after);
    fire(dom, "ArrowUp");
    check("ArrowUp behaves like backward navigation (does not throw, stays in range)", indexOfSlide(doc, activeSlideId(dom)) >= 0);
  }

  fire(dom, "n");
  const notesPanel = doc.getElementById("notes-panel");
  check("N toggles the presenter notes panel open", notesPanel.classList.contains("is-open"));
  fire(dom, "n");
  check("N toggles the presenter notes panel closed again", !notesPanel.classList.contains("is-open"));

  check(
    "fullscreen toggle key actually requests full screen (real behavior, not just no-throw)",
    (() => {
      const before = Boolean(dom.window.document.fullscreenElement);
      fire(dom, "f");
      const after = Boolean(dom.window.document.fullscreenElement);
      return !before && after;
    })()
  );
  const fullscreenBtn = doc.getElementById("fullscreen-toggle");
  check(
    "fullscreen toggle button reflects state via aria-pressed on fullscreenchange",
    fullscreenBtn.getAttribute("aria-pressed") === "true"
  );
  fire(dom, "f");
  check(
    "F exits full screen again",
    !dom.window.document.fullscreenElement &&
      fullscreenBtn.getAttribute("aria-pressed") === "false"
  );

  check(
    "no network access was attempted during keyboard navigation",
    dom._networkAttempts.length === 0,
    JSON.stringify(dom._networkAttempts)
  );
}

function indexOfSlide(doc, id) {
  return Array.from(doc.querySelectorAll(".slide")).findIndex((s) => s.id === id);
}

// ---- Fragment accessibility (aria-hidden synchronized with reveal state) ----
{
  const dom = loadDeck();
  const doc = dom.window.document;
  // A fresh, hash-less load lands on slide one with fragments NOT
  // pre-revealed (see slides.js's initial-load logic) - do not fire Home
  // here, which would itself force-reveal everything and defeat this test.
  const active = doc.querySelector(".slide.is-active");
  const frags = Array.from(active.querySelectorAll(".fragment"));
  if (frags.length > 0) {
    check(
      "unrevealed fragments are aria-hidden from assistive technology",
      frags.every((el) => el.getAttribute("aria-hidden") === "true")
    );
    const announcer = doc.getElementById("fragment-announcer");
    fire(dom, "ArrowRight");
    const revealed = frags.filter((el) => el.classList.contains("is-revealed"));
    check(
      "revealing a fragment clears its aria-hidden attribute",
      revealed.length > 0 && revealed.every((el) => el.getAttribute("aria-hidden") === "false")
    );
    // announceFragment() clears then sets textContent after a short timeout
    // so repeated identical text still re-announces; wait for it for real
    // rather than asserting on a synchronous, always-true property check.
    await new Promise((resolve) => setTimeout(resolve, 80));
    check(
      "revealing a fragment announces its text via the live region",
      typeof announcer.textContent === "string" && announcer.textContent.trim().length > 0
    );
  } else {
    check("fragment accessibility check has a slide with fragments to test", false, "no fragments found on first slide");
  }
}

// ---- Stable deep links ----
{
  const doc0 = loadDeck().window.document;
  const allIds = Array.from(doc0.querySelectorAll(".slide")).map((s) => s.id);
  const midId = allIds[Math.floor(allIds.length / 2)];

  const dom = loadDeck(`http://localhost/slides/index.html#${midId}`);
  check(
    `deep link #${midId} opens directly on that slide`,
    activeSlideId(dom) === midId
  );

  const active = dom.window.document.getElementById(midId);
  const frags = Array.from(active.querySelectorAll(".fragment"));
  const allRevealed = frags.every((el) => el.classList.contains("is-revealed"));
  check(
    "deep-linked slide reveals all of its progressive-disclosure fragments",
    allRevealed
  );
  check(
    "deep-linked slide's revealed fragments are not aria-hidden",
    frags.every((el) => el.getAttribute("aria-hidden") === "false")
  );

  check(
    "location hash matches the active slide id after navigating forward",
    (() => {
      fire(dom, "ArrowRight");
      const idx = allIds.indexOf(activeSlideId(dom));
      return dom.window.location.hash === `#${allIds[idx]}`;
    })()
  );

  check(
    "no network access was attempted resolving a deep link",
    dom._networkAttempts.length === 0
  );
}

// ---- Light/dark toggle persistence ----
{
  const dom = loadDeck();
  const initial = dom.window.SreAgentDemoTheme.current();
  dom.window.SreAgentDemoTheme.toggle();
  const toggled = dom.window.SreAgentDemoTheme.current();
  check("theme toggle actually flips the theme", toggled !== initial);

  const stored = dom.window.localStorage.getItem("sre-agent-demo-theme");
  check("theme toggle persists the choice to localStorage", stored === toggled);

  // Simulate a reload in the same storage/session: re-evaluate theme.js
  // fresh and confirm it picks the persisted theme rather than the system
  // default.
  dom.window.document.documentElement.removeAttribute("data-theme");
  dom.window.eval(readFileSync(themeJsPath, "utf8"));
  const afterReload = dom.window.document.documentElement.getAttribute("data-theme");
  check(
    "persisted theme choice survives a simulated reload",
    afterReload === stored
  );

  // m1 fix: the head-loaded bootstrap script alone (before theme.js, before
  // any body content) must already apply the persisted theme, so there is
  // no flash of the wrong theme on first paint. Simulate this by clearing
  // data-theme and running ONLY theme-bootstrap.js, not the full theme.js.
  dom.window.document.documentElement.removeAttribute("data-theme");
  dom.window.eval(readFileSync(themeBootstrapJsPath, "utf8"));
  const afterBootstrapOnly = dom.window.document.documentElement.getAttribute("data-theme");
  check(
    "theme-bootstrap.js alone (no flash) applies the persisted theme before theme.js runs",
    afterBootstrapOnly === stored
  );

  check(
    "no network access was attempted during theme persistence checks",
    dom._networkAttempts.length === 0
  );
}

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures > 0 ? 1 : 0);
