(function () {
  var REVEAL_SECTIONS_SELECTOR = ".reveal .slides section";
  var ANIMATABLE_SELECTOR = "p, li, pre, blockquote, table, img, figure";

  function isAnimationEnabled() {
    return Boolean(window.config && window.config.animateAllLines);
  }

  function shouldSkipFragment(el) {
    return el.closest("aside.notes") || el.classList.contains("fragment");
  }

  // Add fragment animations to supported elements.
  // Headings are intentionally excluded to keep slide titles static.
  function addFragments() {
    if (!isAnimationEnabled()) {
      return;
    }

    document.querySelectorAll(REVEAL_SECTIONS_SELECTOR).forEach(function (section) {
      section.querySelectorAll(ANIMATABLE_SELECTOR).forEach(function (el) {
        if (shouldSkipFragment(el)) {
          return;
        }
        el.classList.add("fragment");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addFragments);
  } else {
    addFragments();
  }
})();
