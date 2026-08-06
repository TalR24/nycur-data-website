/* Site-wide chrome: slim nav bar under the header + "More from NYCuriosity Data"
   related-work block above the footer. Included on every live page except the
   homepage, the State Capacity Ecosystem section, members, and redirect stubs.
   Related links are curated in /assets/related_work.json, keyed by path prefix. */
(function () {
  var path = location.pathname;
  if (path === '/' || path === '/index.html') return;

  var styleEl = document.createElement('style');
  styleEl.textContent =
    '.sitenav{background:#111827;border-top:1px solid #1f2937;border-bottom:1px solid #1f2937;padding:0 clamp(20px,5vw,48px);}' +
    '.sitenav-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:18px;height:36px;overflow-x:auto;}' +
    '.sitenav a{font-family:\'Roboto Mono\',monospace;font-size:0.7rem;font-weight:600;color:#9ca3af;text-decoration:none;white-space:nowrap;transition:color 0.15s;}' +
    '.sitenav a:hover{color:#fff;}' +
    '.sitenav-spacer{flex:1;}' +
    '.relwork{padding:8px clamp(20px,5vw,48px) 44px;}' +
    '.relwork-inner{max-width:900px;margin:0 auto;}' +
    '.relwork-label{font-family:\'Roboto Mono\',monospace;font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;color:#FF6319;margin-bottom:14px;}' +
    '.relwork-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;}' +
    '.relwork-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:6px;text-decoration:none;box-shadow:0 1px 3px rgba(17,24,39,0.08);transition:border-color 0.2s,box-shadow 0.2s,transform 0.15s;}' +
    '.relwork-card:hover{border-color:#2563eb;transform:translateY(-2px);box-shadow:0 4px 16px rgba(37,99,235,0.10);}' +
    '.relwork-tag{font-family:\'Roboto Mono\',monospace;font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#FF6319;}' +
    '.relwork-title{font-family:\'Roboto Mono\',monospace;font-size:0.85rem;font-weight:700;color:#111827;line-height:1.35;}' +
    '.relwork-cta{font-family:\'Roboto Mono\',monospace;font-size:0.72rem;font-weight:600;color:#2563eb;margin-top:auto;padding-top:4px;}';
  document.head.appendChild(styleEl);

  var header = document.querySelector('header');
  if (header) {
    var bar = document.createElement('nav');
    bar.className = 'sitenav';
    bar.setAttribute('aria-label', 'NYCuriosity Data site navigation');
    bar.innerHTML =
      '<div class="sitenav-inner">' +
      '<a href="/">Home</a>' +
      '<a href="/#tools">All tools</a>' +
      '<a href="/#posts">All posts</a>' +
      '<span class="sitenav-spacer"></span>' +
      '<a href="https://www.nycuriosity.com" target="_blank" rel="noopener">Substack</a>' +
      '</div>';
    header.insertAdjacentElement('afterend', bar);
  }

  fetch('/assets/related_work.json')
    .then(function (r) { return r.json(); })
    .then(function (relMap) {
      var bestKey = null;
      Object.keys(relMap).forEach(function (k) {
        if (path.indexOf(k) === 0 && (!bestKey || k.length > bestKey.length)) bestKey = k;
      });
      if (!bestKey) return;
      var items = relMap[bestKey];
      var footer = document.querySelector('footer');
      if (!footer || !items || !items.length) return;
      var sec = document.createElement('section');
      sec.className = 'relwork';
      sec.innerHTML =
        '<div class="relwork-inner">' +
        '<div class="relwork-label">More from NYCuriosity Data</div>' +
        '<div class="relwork-grid">' +
        items.map(function (it) {
          return '<a class="relwork-card" href="' + it.href + '">' +
            '<span class="relwork-tag">' + it.tag + '</span>' +
            '<span class="relwork-title">' + it.title + '</span>' +
            '<span class="relwork-cta">Explore →</span></a>';
        }).join('') +
        '</div></div>';
      footer.parentNode.insertBefore(sec, footer);
    })
    .catch(function () {});
})();
