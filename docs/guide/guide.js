// Presenter guide behavior: highlights the current section in the sticky
// table of contents as the reader scrolls, using IntersectionObserver (no
// external dependencies).
(function () {
  "use strict";

  var tocLinks = Array.prototype.slice.call(
    document.querySelectorAll(".guide-toc a[href^='#']")
  );
  var linkBySlug = {};
  tocLinks.forEach(function (link) {
    linkBySlug[link.getAttribute("href").slice(1)] = link;
  });

  var sections = Array.prototype.slice.call(
    document.querySelectorAll("section[id]")
  );

  if (!("IntersectionObserver" in window) || sections.length === 0) {
    return;
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        var link = linkBySlug[entry.target.id];
        if (!link) return;
        if (entry.isIntersecting) {
          tocLinks.forEach(function (l) {
            l.classList.remove("is-current");
            l.removeAttribute("aria-current");
          });
          link.classList.add("is-current");
          link.setAttribute("aria-current", "true");
        }
      });
    },
    { rootMargin: "-10% 0px -70% 0px", threshold: 0 }
  );

  sections.forEach(function (section) {
    observer.observe(section);
  });
})();
