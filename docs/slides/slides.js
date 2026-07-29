// Slide deck engine: keyboard/pointer navigation, stable deep links,
// progress indicator, presenter notes panel, and fullscreen. No external
// dependencies; vanilla DOM APIs only.
(function () {
  "use strict";

  var deck = document.getElementById("deck");
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".slide")
  );
  var progressFill = document.getElementById("progress-fill");
  var progressLabel = document.getElementById("progress-label");
  var notesPanel = document.getElementById("notes-panel");
  var notesBody = document.getElementById("notes-body");
  var notesToggle = document.getElementById("notes-toggle");
  var fullscreenToggle = document.getElementById("fullscreen-toggle");
  var prevBtn = document.getElementById("nav-prev");
  var nextBtn = document.getElementById("nav-next");
  var liveRegion = document.getElementById("slide-announcer");
  var fragmentAnnouncer = document.getElementById("fragment-announcer");

  var current = 0;
  var notesOpen = false;

  function slugFor(index) {
    return slides[index].id;
  }

  function indexForSlug(slug) {
    for (var i = 0; i < slides.length; i++) {
      if (slides[i].id === slug) return i;
    }
    return -1;
  }

  function fragmentsIn(slide) {
    return Array.prototype.slice.call(slide.querySelectorAll(".fragment"));
  }

  function resetFragments(slide, revealAll) {
    fragmentsIn(slide).forEach(function (el) {
      var revealed = Boolean(revealAll);
      el.classList.toggle("is-revealed", revealed);
      // Progressive disclosure must hide unrevealed fragments from assistive
      // technology, not just visually (opacity alone leaves them in the
      // accessibility tree, so a screen reader announces "future" slide
      // content immediately). aria-hidden keeps AT and visual state in sync.
      el.setAttribute("aria-hidden", String(!revealed));
    });
  }

  function announceFragment(el) {
    if (!fragmentAnnouncer) return;
    var text = (el.textContent || "").trim().replace(/\s+/g, " ");
    if (!text) return;
    // Clear first so a screen reader re-announces even if the next
    // fragment's text happens to repeat the previous announcement.
    fragmentAnnouncer.textContent = "";
    window.setTimeout(function () {
      fragmentAnnouncer.textContent = text;
    }, 30);
  }

  function updateNotes(slide) {
    var notes = slide.querySelector(".notes");
    notesBody.innerHTML = "";
    if (notes) {
      notesBody.appendChild(notes.cloneNode(true));
      notesBody.firstChild.removeAttribute("hidden");
    } else {
      var empty = document.createElement("p");
      empty.textContent = "No presenter notes for this slide.";
      notesBody.appendChild(empty);
    }
  }

  function render(revealAllFragments) {
    slides.forEach(function (slide, i) {
      var isActive = i === current;
      slide.classList.toggle("is-active", isActive);
      slide.setAttribute("aria-hidden", String(!isActive));
      slide.toggleAttribute("inert", !isActive);
      if (isActive) {
        resetFragments(slide, Boolean(revealAllFragments));
      }
    });

    var pct = slides.length > 1 ? (current / (slides.length - 1)) * 100 : 100;
    progressFill.style.width = pct + "%";
    progressLabel.textContent =
      "Slide " + (current + 1) + " of " + slides.length;

    prevBtn.disabled = current === 0;
    nextBtn.disabled = current === slides.length - 1 && !hasHiddenFragments();

    updateNotes(slides[current]);

    var titleEl = slides[current].querySelector("[data-slide-title]");
    var title = titleEl ? titleEl.textContent.trim() : "";
    liveRegion.textContent =
      "Slide " + (current + 1) + " of " + slides.length + (title ? ": " + title : "");
  }

  function setHash(index, replace) {
    var slug = "#" + slugFor(index);
    if (replace) {
      history.replaceState(null, "", slug);
    } else if (location.hash !== slug) {
      history.pushState(null, "", slug);
    }
  }

  function goTo(index, opts) {
    opts = opts || {};
    if (index < 0 || index >= slides.length) return;
    current = index;
    render(opts.revealAllFragments);
    setHash(index, opts.replace);
    if (opts.focus !== false) {
      slides[current].focus({ preventScroll: true });
    }
  }

  function hasHiddenFragments() {
    var frags = fragmentsIn(slides[current]);
    return frags.some(function (el) {
      return !el.classList.contains("is-revealed");
    });
  }

  function nextFragmentOrSlide() {
    var frags = fragmentsIn(slides[current]);
    var nextHidden = frags.find(function (el) {
      return !el.classList.contains("is-revealed");
    });
    if (nextHidden) {
      nextHidden.classList.add("is-revealed");
      nextHidden.setAttribute("aria-hidden", "false");
      announceFragment(nextHidden);
      nextBtn.disabled =
        current === slides.length - 1 && !hasHiddenFragments();
      return;
    }
    goTo(current + 1);
  }

  function prevSlide() {
    goTo(current - 1, { revealAllFragments: true });
  }

  function toggleNotes(forceOpen) {
    notesOpen = typeof forceOpen === "boolean" ? forceOpen : !notesOpen;
    notesPanel.classList.toggle("is-open", notesOpen);
    notesPanel.setAttribute("aria-hidden", String(!notesOpen));
    notesToggle.setAttribute("aria-pressed", String(notesOpen));
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      (deck.requestFullscreen || deck.webkitRequestFullscreen || function () {}).call(
        deck
      );
    } else {
      (document.exitFullscreen || document.webkitExitFullscreen || function () {}).call(
        document
      );
    }
  }

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = el.tagName ? el.tagName.toLowerCase() : "";
    return (
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      el.isContentEditable
    );
  }

  document.addEventListener("keydown", function (evt) {
    if (isTypingTarget(evt.target)) return;

    switch (evt.key) {
      case "ArrowRight":
      case "ArrowDown":
      case " ":
      case "PageDown":
        evt.preventDefault();
        nextFragmentOrSlide();
        break;
      case "ArrowLeft":
      case "ArrowUp":
      case "PageUp":
        evt.preventDefault();
        prevSlide();
        break;
      case "Home":
        evt.preventDefault();
        goTo(0, { revealAllFragments: true });
        break;
      case "End":
        evt.preventDefault();
        goTo(slides.length - 1, { revealAllFragments: true });
        break;
      case "f":
      case "F":
        evt.preventDefault();
        toggleFullscreen();
        break;
      case "n":
      case "N":
        evt.preventDefault();
        toggleNotes();
        break;
      case "Escape":
        if (notesOpen) toggleNotes(false);
        break;
      default:
        break;
    }
  });

  prevBtn.addEventListener("click", prevSlide);
  nextBtn.addEventListener("click", nextFragmentOrSlide);
  notesToggle.addEventListener("click", function () {
    toggleNotes();
  });
  fullscreenToggle.addEventListener("click", toggleFullscreen);

  window.addEventListener("popstate", function () {
    var slug = location.hash.replace(/^#/, "");
    var idx = indexForSlug(slug);
    goTo(idx === -1 ? 0 : idx, { revealAllFragments: true, replace: true, focus: false });
  });

  document.addEventListener("fullscreenchange", function () {
    var active = Boolean(document.fullscreenElement);
    fullscreenToggle.setAttribute("aria-pressed", String(active));
  });

  // Initial slide from a deep link, if present and valid. Only force all
  // fragments revealed when actually arriving via a deep link (matches the
  // Home/End/popstate behavior below) - a plain, hash-less load of the deck
  // lands on the first slide and preserves progressive disclosure there too,
  // instead of unconditionally spoiling it on slide one.
  var initialSlug = location.hash.replace(/^#/, "");
  var initialIndex = indexForSlug(initialSlug);
  goTo(initialIndex === -1 ? 0 : initialIndex, {
    revealAllFragments: initialIndex !== -1,
    replace: true,
    focus: false,
  });
})();
