(function () {
  var REVEAL_SECTIONS_SELECTOR = ".reveal .slides section";
  var ANIMATABLE_SELECTOR = "*";
  var EXCLUDED_TAGS = new Set([
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "SECTION",
    "ASIDE",
    "SCRIPT",
    "STYLE",
    "TEMPLATE",
    "LINK",
    "META",
    "TITLE",
    "HEAD",
    "BODY",
    "HTML"
  ]);
  var SELF_ANIMATABLE_TAGS = new Set([
    "TABLE",
    "FIGURE",
    "VIDEO",
    "AUDIO",
    "CANVAS",
    "SVG",
    "PRE",
    "BLOCKQUOTE"
  ]);

  function isAnimationEnabled() {
    return Boolean(window.config && window.config.animateAllLines);
  }

  function shouldSkipFragment(el) {
    return el.closest("aside.notes") || el.classList.contains("fragment");
  }

  function isEligibleElement(el, skipChildrenCheck) {
    if (EXCLUDED_TAGS.has(el.tagName) || shouldSkipFragment(el)) {
      return false;
    }

    if (skipChildrenCheck) {
      return true;
    }

    if (SELF_ANIMATABLE_TAGS.has(el.tagName)) {
      return true;
    }

    // Avoid animating wrapper elements when they contain other eligible items.
    for (var i = 0; i < el.children.length; i += 1) {
      if (isEligibleElement(el.children[i], true)) {
        return false;
      }
    }

    return true;
  }

  // Add fragment animations to supported elements.
  // Headings are intentionally excluded to keep slide titles static.
  function addFragments() {
    if (!isAnimationEnabled()) {
      return;
    }

    document.querySelectorAll(REVEAL_SECTIONS_SELECTOR).forEach(function (section) {
      section.querySelectorAll(ANIMATABLE_SELECTOR).forEach(function (el) {
        if (isEligibleElement(el, false)) {
          el.classList.add("fragment");
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addFragments);
  } else {
    addFragments();
  }
})();
