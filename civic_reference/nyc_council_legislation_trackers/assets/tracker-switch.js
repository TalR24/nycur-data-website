/* Tracker switcher: one bar on every Council tracker page for moving between
 * the three trackers (Fiscal Impacts, Obligations, Powers). Inserted above the
 * page's own view row (.pill-nav / .chart-nav), or above the hero on pages
 * without one. Each button opens that tracker's table, its main feature.
 * The current tracker is read from the URL; law/ and methodology/ are shared
 * by Obligations and Powers, so nothing is highlighted there.
 * Include with: <script defer src="/civic_reference/nyc_council_legislation_trackers/assets/tracker-switch.js"></script>
 */
(function () {
  var BASE = '/civic_reference/';
  var TRACKERS = [
    { key: 'fiscal', label: 'Fiscal Impacts', note: 'what it costs',
      href: BASE + 'nyc_council_fiscal_impacts_tracker/', ink: '--b-topic-budget-ink' },
    { key: 'obligations', label: 'Obligations', note: 'what it requires',
      href: BASE + 'legislation_implementation_tracker/obligations-table/', ink: '--b-topic-transit-ink' },
    { key: 'powers', label: 'Powers', note: 'what it allows',
      href: BASE + 'legislation_implementation_tracker/powers-table/', ink: '--b-topic-cb-ink' }
  ];

  function current() {
    var p = location.pathname;
    if (p.indexOf('/nyc_council_fiscal_impacts_tracker/') !== -1) return 'fiscal';
    if (p.indexOf('/legislation_implementation_tracker/') === -1) return null;
    if (/\/(powers|powers-table)\//.test(p)) return 'powers';
    if (/\/(law|methodology|alerts)\//.test(p)) return null;
    return 'obligations';
  }

  function css() {
    if (document.getElementById('trk-switch-css')) return;
    var s = document.createElement('style');
    s.id = 'trk-switch-css';
    s.textContent =
      '.trk-switch{background:var(--b-cream,var(--bg));border-bottom:1px solid var(--border);' +
      'padding:10px clamp(20px,5vw,48px);display:flex;gap:8px;flex-wrap:wrap;align-items:center}' +
      '.trk-switch .trk-label{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.72rem;' +
      'color:var(--text-muted);white-space:nowrap;margin-right:2px}' +
      '.trk-switch a.trk{--ink:var(--blue);display:inline-flex;align-items:baseline;gap:7px;' +
      'font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.8rem;font-weight:700;' +
      'padding:5px 13px;border-radius:8px;text-decoration:none;color:var(--ink);' +
      'border:1.5px solid var(--ink);background:var(--surface,#fff);transition:background .15s,color .15s}' +
      '.trk-switch a.trk .trk-note{font-weight:500;font-size:.7rem;opacity:.85}' +
      '.trk-switch a.trk:hover{background:var(--ink);color:#fff}' +
      '.trk-switch a.trk.active{background:var(--ink);color:#fff}' +
      '.trk-switch a.trk-all{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.74rem;' +
      'color:var(--text-muted);text-decoration:none;margin-left:6px;white-space:nowrap}' +
      '.trk-switch a.trk-all:hover{color:var(--text)}' +
      '@media (max-width:560px){.trk-switch a.trk .trk-note{display:none}}';
    document.head.appendChild(s);
  }

  function build() {
    if (document.querySelector('.trk-switch')) return;
    var cur = current();
    var bar = document.createElement('nav');
    bar.className = 'trk-switch';
    bar.setAttribute('aria-label', 'Council legislation trackers');
    var html = '<span class="trk-label">Trackers:</span>';
    TRACKERS.forEach(function (t) {
      html += '<a class="trk' + (t.key === cur ? ' active' : '') + '" href="' + t.href + '"' +
        ' style="--ink:var(' + t.ink + ')"' + (t.key === cur ? ' aria-current="page"' : '') + '>' +
        t.label + ' <span class="trk-note">' + t.note + '</span></a>';
    });
    html += '<a class="trk-all" href="' + BASE + 'nyc_council_legislation_trackers/">All trackers &rarr;</a>';
    bar.innerHTML = html;
    // top of the page's own content: right under the site nav (site.js puts
    // .sitenav directly after <header>; if it arrives later it still lands
    // between the header and this bar), so the order is header, nav, trackers
    var after = document.querySelector('.sitenav') || document.querySelector('body > header');
    if (after && after.parentNode) {
      after.insertAdjacentElement('afterend', bar);
    } else {
      var anchor = document.querySelector('.pill-nav, .chart-nav, .hero, main');
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(bar, anchor);
    }
    css();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
