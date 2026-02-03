(function () {
    function getConfig() {
        var script = document.currentScript;
        if (!script) {
            var scripts = document.getElementsByTagName('script');
            script = scripts[scripts.length - 1];
        }
        var dataset = script && script.dataset ? script.dataset : {};
        return {
            footerText: dataset.footerText || '',
            animateAllLines: dataset.animateAllLines === 'true',
            presentation: dataset.presentation === 'true'
        };
    }

    var cfg = getConfig();
    window.config = {
        footerText: cfg.footerText,
        animateAllLines: cfg.animateAllLines
    };

    if (cfg.presentation && cfg.animateAllLines) {
        function addFragments() {
            var selector = 'p, li, h1, h2, h3, h4, h5, h6, pre, blockquote, table, img, figure';
            document.querySelectorAll('.reveal .slides section').forEach(function (section) {
                section.querySelectorAll(selector).forEach(function (el) {
                    if (el.closest('aside.notes')) return;
                    if (el.classList.contains('fragment')) return;
                    el.classList.add('fragment');
                });
            });
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', addFragments);
        } else {
            addFragments();
        }
    }
})();
