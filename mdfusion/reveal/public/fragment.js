(function () {
  function shouldAnimate() {
    if (!window.config || !window.config.animateAllLines) {
      return false;
    }
    return true;
  }

  function addFragments() {
    if (!shouldAnimate()) {
      return;
    }
    var selector = "p, li, h1, h2, h3, h4, h5, h6, pre, blockquote, table, img, figure";
    document.querySelectorAll(".reveal .slides section").forEach(function (section) {
      section.querySelectorAll(selector).forEach(function (el) {
        if (el.closest("aside.notes")) return;
        if (el.classList.contains("fragment")) return;
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
