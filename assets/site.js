/* Site-wide chrome: slim nav bar with Tools/Posts dropdowns under the header +
   "More from NYCuriosity Data" related-work block above the footer.
   Included on every live page (incl. the homepage) except the State Capacity
   Ecosystem section, /members/, and redirect stubs. The related-work block is
   curated in /assets/related_work.json, keyed by path prefix; the homepage
   never shows it. When a tool or post hub ships, add it to TOOLS_MENU or
   POSTS_MENU below (posts newest first). */
(function () {
  var path = location.pathname;
  var isHome = path === '/' || path === '/index.html';

  var TOOLS_MENU = [
    { label: 'NYC Council Legislation Trackers', href: '/civic_reference/nyc_council_legislation_trackers/' },
    { label: 'Legislation Implementation Tracker', href: '/civic_reference/legislation_implementation_tracker/' },
    { label: 'Fiscal Impacts Tracker', href: '/civic_reference/nyc_council_fiscal_impacts_tracker/' },
    { label: 'Council Members', href: '/civic_reference/nyc_council_legislation_trackers/council-members/' },
    { label: 'CB Member Tracker', href: '/cb-tools/member-tracker/' },
    { label: 'Community Board Tools', href: '/cb-tools/' },
    { label: 'CB Member Field Guide', href: '/civic_reference/cb_member_guide/' },
    { label: 'NYC Government Bodies Explorer', href: '/civic_reference/nyc-gov-bodies-explorer/' },
    { label: 'State Capacity Ecosystem', href: '/state_capacity_ecosystem/' }
  ];
  var POSTS_MENU = [
    { label: 'What the Council Asks of NYC Agencies', href: '/nycuriosity_substack_posts/council_obligations/' },
    { label: 'Suggestions to Improve NYC Community Boards', href: '/nycuriosity_substack_posts/community_board_suggestions/' },
    { label: 'West 4th St Station Deep Dive', href: '/nycuriosity_substack_posts/west_4th_st_station/' },
    { label: "Medicaid's Check Register Is Public", href: '/nycuriosity_substack_posts/medicaid_provider_spending/' },
    { label: 'State Capacity Has a New Toolkit', href: '/nycuriosity_substack_posts/state_capacity_ai/' },
    { label: 'New York Needs to Grow', href: '/nycuriosity_substack_posts/nyc_building_strategies/' },
    { label: 'QueensWay vs QueensLink', href: '/nycuriosity_substack_posts/queensway_vs_queenslink/' },
    { label: "Lessons from Mamdani's First 100 Days", href: '/nycuriosity_substack_posts/mamdani_100_days/' },
    { label: 'What Has MCB3 Focused On Over Time?', href: '/nycuriosity_substack_posts/mcb3_history_analysis/' },
    { label: 'Chief Savings Officer Reports', href: '/nycuriosity_substack_posts/cso_reports_2026/' },
    { label: 'Local Law 195 Data', href: '/nycuriosity_substack_posts/streets_plan_2026/' }
  ];

  var styleEl = document.createElement('style');
  styleEl.textContent =
    '.sitenav{background:#111827;border-top:1px solid #1f2937;border-bottom:1px solid #1f2937;padding:0 clamp(20px,5vw,48px);}' +
    '.sitenav-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:4px 18px;min-height:36px;flex-wrap:wrap;padding:2px 0;}' +
    '.sitenav a,.sitenav-btn{font-family:\'Roboto Mono\',monospace;font-size:0.7rem;font-weight:600;color:#9ca3af;text-decoration:none;white-space:nowrap;transition:color 0.15s;background:none;border:none;padding:8px 0;cursor:pointer;}' +
    '.sitenav a:hover,.sitenav-btn:hover{color:#fff;}' +
    '.sitenav-item{position:relative;}' +
    '.sitenav-item.open .sitenav-btn{color:#fff;}' +
    '.sitenav-caret{font-size:0.6rem;margin-left:3px;}' +
    '.sitenav-menu{display:none;position:absolute;top:100%;left:0;z-index:200;background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;box-shadow:0 8px 24px rgba(17,24,39,0.16);padding:8px;min-width:280px;max-height:60vh;overflow-y:auto;}' +
    '.sitenav-item.open .sitenav-menu{display:block;}' +
    '.sitenav-menu a{display:block;padding:7px 10px;border-radius:6px;color:#374151;font-size:0.74rem;white-space:normal;line-height:1.4;}' +
    '.sitenav-menu a:hover{background:#eff6ff;color:#2563eb;}' +
    '.sitenav-menu .menu-all{color:#2563eb;border-top:1px solid #e5e7eb;border-radius:0 0 6px 6px;margin-top:6px;padding-top:10px;}' +
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

  function menuHtml(items, allLabel, allHref) {
    return items.map(function (it) {
      return '<a href="' + it.href + '">' + it.label + '</a>';
    }).join('') + '<a class="menu-all" href="' + allHref + '">' + allLabel + '</a>';
  }

  var header = document.querySelector('header');
  if (header) {
    var bar = document.createElement('nav');
    bar.className = 'sitenav';
    bar.setAttribute('aria-label', 'NYCuriosity Data site navigation');
    bar.innerHTML =
      '<div class="sitenav-inner">' +
      (isHome ? '' : '<a href="/">Home</a>') +
      '<div class="sitenav-item">' +
      '<button type="button" class="sitenav-btn" aria-expanded="false" aria-haspopup="true">Tools<span class="sitenav-caret">▾</span></button>' +
      '<div class="sitenav-menu">' + menuHtml(TOOLS_MENU, 'All tools →', '/#tools') + '</div>' +
      '</div>' +
      '<div class="sitenav-item">' +
      '<button type="button" class="sitenav-btn" aria-expanded="false" aria-haspopup="true">Posts<span class="sitenav-caret">▾</span></button>' +
      '<div class="sitenav-menu">' + menuHtml(POSTS_MENU, 'All posts →', '/#posts') + '</div>' +
      '</div>' +
      '<span class="sitenav-spacer"></span>' +
      '<a href="https://www.nycuriosity.com" target="_blank" rel="noopener">Substack</a>' +
      '</div>';
    header.insertAdjacentElement('afterend', bar);

    var items = bar.querySelectorAll('.sitenav-item');
    items.forEach(function (item) {
      var btn = item.querySelector('.sitenav-btn');
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var wasOpen = item.classList.contains('open');
        items.forEach(function (other) {
          other.classList.remove('open');
          other.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'false');
        });
        if (!wasOpen) {
          item.classList.add('open');
          btn.setAttribute('aria-expanded', 'true');
        }
      });
    });
    document.addEventListener('click', function () {
      items.forEach(function (item) {
        item.classList.remove('open');
        item.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'false');
      });
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        items.forEach(function (item) {
          item.classList.remove('open');
          item.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'false');
        });
      }
    });
  }

  if (isHome) return;

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
