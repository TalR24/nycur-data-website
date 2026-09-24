/* CB tools switcher: one bar on every Community Board tool page for moving
 * between the six CB tools. Inserted after .sitenav (or body > header if the
 * nav has not landed yet), mirroring the Council trackers' tracker-switch.js.
 * The current tool is read from the URL.
 * Include with: <script defer src="/cb-tools/cb-switch.js"></script>
 */
(function () {
  var INK = '--b-topic-cb-ink';
  var TOOLS = [
    { key: 'member-tracker', label: 'Member Tracker', href: '/cb-tools/member-tracker/' },
    { key: 'cb_member_guide', label: 'Member Guide', href: '/civic_reference/cb_member_guide/' },
    { key: 'roberts-rules-helper', label: "Robert's Rules", href: '/cb-tools/roberts-rules-helper/' },
    { key: 'meeting-review', label: 'Meeting Review', href: '/cb-tools/meeting-review/' },
    { key: 'board-scorecard', label: 'Scorecard', href: '/cb-tools/board-scorecard/' },
    { key: 'block-party', label: 'Block Party', href: '/cb-tools/block-party/' }
  ];
  var BLOCK_PARTY_PATHS = [
    '/cb-tools/block-party/', '/cb-tools/block_party_july2026/',
    '/cb-tools/resolutions-per-year/', '/cb-tools/top-agencies/',
    '/cb-tools/top-topics/', '/cb-tools/explorer/', '/cb-tools/sogt-2026/',
    '/cb-tools/school-of-data-2026/'
  ];

  function current() {
    var p = location.pathname;
    if (p.indexOf('/civic_reference/cb_member_guide/') !== -1) return 'cb_member_guide';
    for (var i = 0; i < BLOCK_PARTY_PATHS.length; i++) {
      if (p.indexOf(BLOCK_PARTY_PATHS[i]) !== -1) return 'block-party';
    }
    if (p.indexOf('/cb-tools/member-tracker/') !== -1) return 'member-tracker';
    if (p.indexOf('/cb-tools/roberts-rules-helper/') !== -1) return 'roberts-rules-helper';
    if (p.indexOf('/cb-tools/meeting-review/') !== -1) return 'meeting-review';
    if (p.indexOf('/cb-tools/board-scorecard/') !== -1) return 'board-scorecard';
    return null;
  }

  function css() {
    if (document.getElementById('cb-switch-css')) return;
    var s = document.createElement('style');
    s.id = 'cb-switch-css';
    s.textContent =
      '.cb-switch{background:var(--b-cream,var(--bg));border-bottom:1px solid var(--border);' +
      'padding:10px clamp(20px,5vw,48px);display:flex;gap:8px;flex-wrap:wrap;align-items:center}' +
      '.cb-switch .cb-label{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.72rem;' +
      'color:var(--text-muted);white-space:nowrap;margin-right:2px}' +
      '.cb-switch a.cbt{--ink:var(' + INK + ');display:inline-flex;align-items:baseline;gap:7px;' +
      'font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.8rem;font-weight:700;' +
      'padding:5px 13px;border-radius:8px;text-decoration:none;color:var(--ink);' +
      'border:1.5px solid var(--ink);background:var(--surface,#fff);transition:background .15s,color .15s}' +
      '.cb-switch a.cbt:hover{background:var(--ink);color:#fff}' +
      '.cb-switch a.cbt.active{background:var(--ink);color:#fff}' +
      '.cb-switch a.cbt-all{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:.74rem;' +
      'color:var(--text-muted);text-decoration:none;margin-left:6px;white-space:nowrap}' +
      '.cb-switch a.cbt-all:hover{color:var(--text)}';
    document.head.appendChild(s);
  }

  function build() {
    if (document.querySelector('.cb-switch')) return;
    var cur = current();
    var bar = document.createElement('nav');
    bar.className = 'cb-switch';
    bar.setAttribute('aria-label', 'Community board tools');
    var html = '<span class="cb-label">CB tools:</span>';
    TOOLS.forEach(function (t) {
      html += '<a class="cbt' + (t.key === cur ? ' active' : '') + '" href="' + t.href + '"' +
        (t.key === cur ? ' aria-current="page"' : '') + '>' + t.label + '</a>';
    });
    html += '<a class="cbt-all" href="/cb-tools/">All tools &rarr;</a>';
    bar.innerHTML = html;
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
