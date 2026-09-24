/* Tracker switcher: one bar on every Council tracker page for moving between
 * the three trackers (Fiscal Impacts, Obligations, Powers). Inserted above the
 * page's own view row (.pill-nav / .chart-nav), or above the hero on pages
 * without one. Each button opens that tracker's overview page (Tal, Sep 24 2026).
 * The current tracker is read from the URL; law/ and methodology/ are shared
 * by Obligations and Powers, so nothing is highlighted there.
 * Include with: <script defer src="/civic_reference/nyc_council_legislation_trackers/assets/tracker-switch.js"></script>
 */
(function () {
  var BASE = '/civic_reference/';
  var TRACKERS = [
    { key: 'fiscal', label: 'Fiscal Impacts', note: 'what it costs',
      href: BASE + 'nyc_council_fiscal_impacts_tracker/overview/', ink: '--b-topic-budget-ink' },
    { key: 'obligations', label: 'Obligations', note: 'what it requires',
      href: BASE + 'legislation_implementation_tracker/', ink: '--b-topic-transit-ink' },
    { key: 'powers', label: 'Powers', note: 'what it allows',
      href: BASE + 'legislation_implementation_tracker/powers/', ink: '--b-topic-cb-ink' }
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
    studioCallout();
  }

  // NYCuriosity Studio callout above the footer of every tracker page (Tal, Sep 24 2026)
  function studioCallout() {
    if (document.querySelector('.trk-studio')) return;
    var foot = document.querySelector('body > footer');
    if (!foot) return;
    var box = document.createElement('aside');
    box.className = 'trk-studio';
    box.innerHTML = '<div class="trk-studio-inner"><div><p class="trk-studio-k">NYCuriosity Studio</p>' +
      '<p class="trk-studio-h">Need a tracker like this for your records?</p>' +
      '<p class="trk-studio-p">I build trackers, dashboards and searchable archives from public records, on commission.</p></div>' +
      '<div class="trk-studio-btns"><a href="https://talroded.nycuriosity.com/services/case-studies/legislation-trackers/">How these trackers were built</a>' +
      '<a class="primary" href="https://talroded.nycuriosity.com/services/#start">Start a project &rarr;</a></div></div>';
    foot.parentNode.insertBefore(box, foot);
    if (document.getElementById('trk-studio-css')) return;
    var s = document.createElement('style');
    s.id = 'trk-studio-css';
    s.textContent =
      '.trk-studio{padding:0 clamp(20px,5vw,48px) clamp(32px,5vw,48px)}' +
      '.trk-studio-inner{max-width:1100px;margin:0 auto;background:var(--surface,#fff);border:1px solid var(--border);' +
      'border-left:4px solid var(--b-tangerine-deep,var(--blue));border-radius:12px;padding:20px 24px;display:flex;flex-wrap:wrap;' +
      'gap:16px;align-items:center;justify-content:space-between}' +
      '.trk-studio-k{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.68rem;font-weight:700;text-transform:uppercase;' +
      'letter-spacing:.09em;color:var(--b-tangerine-deep,var(--blue));margin:0 0 4px}' +
      '.trk-studio-h{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:1rem;font-weight:700;color:var(--text);margin:0 0 4px}' +
      '.trk-studio-p{font-size:.88rem;color:var(--text-muted);margin:0}' +
      '.trk-studio-btns{display:flex;gap:10px;flex-wrap:wrap}' +
      '.trk-studio-btns a{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.78rem;font-weight:600;text-decoration:none;' +
      'padding:9px 16px;border-radius:8px;border:1px solid var(--border);color:var(--text);white-space:nowrap}' +
      '.trk-studio-btns a:hover{border-color:var(--b-tangerine-deep,var(--blue))}' +
      '.trk-studio-btns a.primary{background:var(--b-tangerine-deep,var(--blue));border-color:var(--b-tangerine-deep,var(--blue));color:var(--b-surface,#fff)}';
    document.head.appendChild(s);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
