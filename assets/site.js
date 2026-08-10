/* Site-wide chrome: pill-style nav bar with two-level Tools / category-grouped
   Posts dropdowns under the header + "More from NYCuriosity Data" related-work
   block above the footer. Included on every live page (incl. the homepage)
   except the State Capacity Ecosystem section, /members/, and redirect stubs.
   Related work is curated in /assets/related_work.json (path-prefix keys).
   When a tool or post hub ships: add it to TOOLS_MENU (with sub list) or the
   right POSTS_MENU category (newest first, max 2 shown). Sub lists cap at 5
   items; the flyout always ends with a See-all link to the hub. */
(function () {
  var path = location.pathname;
  var isHome = path === '/' || path === '/index.html';

  var TOOLS_MENU = [
    { label: 'NYC Council Legislation Trackers', href: '/civic_reference/nyc_council_legislation_trackers/', sub: [
      { label: 'Implementation Tracker', href: '/civic_reference/legislation_implementation_tracker/' },
      { label: 'Fiscal Impacts Tracker', href: '/civic_reference/nyc_council_fiscal_impacts_tracker/' },
      { label: 'Council Members', href: '/civic_reference/nyc_council_legislation_trackers/council-members/' },
      { label: 'Email alerts', href: '/civic_reference/legislation_implementation_tracker/alerts/' }
    ]},
    { label: 'CB Member Tracker', href: '/cb-tools/member-tracker/', sub: [
      { label: 'Term-limit openings', href: '/cb-tools/member-tracker/openings/' },
      { label: 'Email alerts', href: '/cb-tools/member-tracker/alerts/' },
      { label: 'Methodology', href: '/cb-tools/member-tracker/methodology/' }
    ]},
    { label: 'Community Board Tools', href: '/cb-tools/', sub: [
      { label: 'Block Party archive', href: '/cb-tools/block-party/' },
      { label: 'Robert’s Rules helper', href: '/cb-tools/roberts-rules-helper/' },
      { label: 'AI meeting review', href: '/cb-tools/meeting-review/' },
      { label: 'Board scorecard', href: '/cb-tools/board-scorecard/' }
    ]},
    { label: 'CB Member Field Guide', href: '/civic_reference/cb_member_guide/' },
    { label: 'NYC Government Bodies Explorer', href: '/civic_reference/nyc-gov-bodies-explorer/', sub: [
      { label: 'Methodology', href: '/civic_reference/nyc-gov-bodies-explorer/methodology/' }
    ]},
    { label: 'State Capacity Ecosystem', href: '/state_capacity_ecosystem/' }
  ];

  var POSTS_MENU = [
    { cat: 'Transit & Streets', topic: 'transit', items: [
      { label: 'West 4th St Station Deep Dive', href: '/nycuriosity_substack_posts/west_4th_st_station/' },
      { label: 'New York Needs to Grow', href: '/nycuriosity_substack_posts/nyc_building_strategies/' }
    ]},
    { cat: 'Community Boards', topic: 'cb', items: [
      { label: 'Suggestions to Improve NYC Community Boards', href: '/nycuriosity_substack_posts/community_board_suggestions/' },
      { label: 'What Has MCB3 Focused On Over Time?', href: '/nycuriosity_substack_posts/mcb3_history_analysis/' }
    ]},
    { cat: 'Budget & Policy', topic: 'budget', items: [
      { label: 'What the Council Asks of NYC Agencies', href: '/nycuriosity_substack_posts/council_obligations/' },
      { label: 'Medicaid’s Check Register Is Public', href: '/nycuriosity_substack_posts/medicaid_provider_spending/' }
    ]},
    { cat: 'Government & Technology', topic: 'govtech', items: [
      { label: 'What Mamdani’s Efficiency Commission Put on the Ballot', href: '/nycuriosity_substack_posts/coge_report/' },
      { label: 'State Capacity Has a New Toolkit', href: '/nycuriosity_substack_posts/state_capacity_ai/' }
    ]}
  ];

  var styleEl = document.createElement('style');
  styleEl.textContent =
    '.sitenav{background:#111827;border-top:1px solid #1f2937;border-bottom:1px solid #1f2937;padding:0 clamp(20px,5vw,48px);}' +
    '.sitenav-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:10px;min-height:52px;flex-wrap:wrap;padding:8px 0;}' +
    '.sitenav .nav-pill,.sitenav-btn{font-family:\'Roboto Mono\',monospace;font-size:0.8rem;font-weight:600;color:#e5e7eb;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.22);border-radius:20px;padding:7px 16px;text-decoration:none;white-space:nowrap;cursor:pointer;transition:all 0.15s;display:inline-flex;align-items:center;gap:6px;}' +
    '.sitenav .nav-pill:hover,.sitenav-btn:hover,.sitenav-item.open .sitenav-btn{background:#2563eb;border-color:#2563eb;color:#fff;}' +
    '.sitenav-item{position:relative;}' +
    '.sitenav-caret{font-size:0.6rem;}' +
    '.sitenav-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;z-index:200;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;box-shadow:0 10px 28px rgba(17,24,39,0.18);padding:10px;min-width:310px;max-height:72vh;overflow-y:auto;}' +
    '.sitenav-menu--tools{max-height:none;overflow:visible;}' +
    '.sitenav-item.open .sitenav-menu{display:block;}' +
    '.sitenav-menu a{display:block;padding:7px 10px;border-radius:6px;color:#374151;font-family:\'Roboto Mono\',monospace;font-size:0.74rem;font-weight:600;text-decoration:none;white-space:normal;line-height:1.4;}' +
    '.sitenav-menu a:hover{background:#eff6ff;color:#2563eb;}' +
    '.menu-cat{font-family:\'Roboto Mono\',monospace;font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing:0.09em;color:#FF6319;padding:10px 10px 4px;}' +
    '.menu-cat:first-child{padding-top:4px;}' +
    '.sitenav-menu .menu-seeall{color:#2563eb;font-size:0.7rem;padding-top:3px;padding-bottom:9px;border-bottom:1px solid #f3f4f6;border-radius:0;margin-bottom:2px;}' +
    '.sitenav-menu .menu-all{color:#2563eb;border-top:1px solid #e5e7eb;border-radius:0 0 8px 8px;margin-top:6px;padding-top:10px;}' +
    '.menu-group{position:relative;}' +
    '.menu-row{display:flex;align-items:center;gap:2px;}' +
    '.menu-row .menu-link{flex:1;}' +
    '.sub-toggle{flex-shrink:0;background:none;border:none;color:#9ca3af;font-size:0.7rem;padding:6px 8px;cursor:pointer;border-radius:6px;}' +
    '.sub-toggle:hover{background:#eff6ff;color:#2563eb;}' +
    '.sitenav-sub{display:none;position:absolute;left:100%;top:-10px;margin-left:8px;z-index:210;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;box-shadow:0 10px 28px rgba(17,24,39,0.18);padding:8px;min-width:240px;}' +
    /* Invisible bridge over the 8px gap (and a little above/below) so the
       pointer can cross from the menu row into the flyout without the group
       losing hover. Works with the JS grace timers below. */
    '.sitenav-sub::before{content:\'\';position:absolute;top:-10px;bottom:-10px;left:-18px;width:18px;}' +
    '.menu-group.sub-hover > .sitenav-sub{display:block;}' +
    '.menu-group.sub-open > .sitenav-sub{display:block;position:static;margin:2px 0 6px 14px;border:none;box-shadow:none;border-left:2px solid #e5e7eb;border-radius:0;padding:0 0 0 8px;min-width:0;}' +
    '.sitenav-spacer{flex:1;}' +
    '.relwork{padding:8px clamp(20px,5vw,48px) 44px;}' +
    '.relwork-inner{max-width:900px;margin:0 auto;}' +
    '.relwork-label{font-family:\'Roboto Mono\',monospace;font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;color:#FF6319;margin-bottom:14px;}' +
    '.relwork-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;}' +
    '.relwork-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:6px;text-decoration:none;box-shadow:0 1px 3px rgba(17,24,39,0.08);transition:border-color 0.2s,box-shadow 0.2s,transform 0.15s;}' +
    '.relwork-card:hover{border-color:#2563eb;transform:translateY(-2px);box-shadow:0 4px 16px rgba(37,99,235,0.10);}' +
    '.relwork-tag{font-family:\'Roboto Mono\',monospace;font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#FF6319;}' +
    '.relwork-title{font-family:\'Roboto Mono\',monospace;font-size:0.85rem;font-weight:700;color:#111827;line-height:1.35;}' +
    '.relwork-cta{font-family:\'Roboto Mono\',monospace;font-size:0.72rem;font-weight:600;color:#2563eb;margin-top:auto;padding-top:4px;}' +
    /* The footer nav is a flex row with no wrap in every page's local CSS, so
       on a 360px screen it measures 490px and pushes the whole page into
       horizontal scroll. Patched here because site.js is the one stylesheet
       shared across the site. Pages without site.js (SCE, /members/, redirect
       stubs) still need this locally. */
    '.footer-links{flex-wrap:wrap;}';
  document.head.appendChild(styleEl);

  function toolsHtml() {
    return TOOLS_MENU.map(function (t) {
      if (!t.sub || !t.sub.length) {
        return '<a class="menu-link" href="' + t.href + '">' + t.label + '</a>';
      }
      var shown = t.sub.slice(0, 5);
      var subLinks = shown.map(function (s) {
        return '<a href="' + s.href + '">' + s.label + '</a>';
      }).join('') + '<a class="menu-all" href="' + t.href + '">See all →</a>';
      return '<div class="menu-group">' +
        '<div class="menu-row"><a class="menu-link" href="' + t.href + '">' + t.label + '</a>' +
        '<button type="button" class="sub-toggle" aria-label="Show subpages of ' + t.label + '">▸</button></div>' +
        '<div class="sitenav-sub">' + subLinks + '</div></div>';
    }).join('') + '<a class="menu-all" href="/#tools">All tools →</a>';
  }

  function postsHtml() {
    return POSTS_MENU.map(function (g) {
      return '<div class="menu-cat">' + g.cat + '</div>' +
        g.items.slice(0, 2).map(function (p) {
          return '<a href="' + p.href + '">' + p.label + '</a>';
        }).join('') +
        '<a class="menu-seeall" href="/?topic=' + g.topic + '#posts">See all ' + g.cat + ' →</a>';
    }).join('') + '<a class="menu-all" href="/#posts">All posts →</a>';
  }

  var header = document.querySelector('header');
  if (header) {
    var bar = document.createElement('nav');
    bar.className = 'sitenav';
    bar.setAttribute('aria-label', 'NYCuriosity Data site navigation');
    bar.innerHTML =
      '<div class="sitenav-inner">' +
      (isHome ? '' : '<a class="nav-pill" href="/">Home</a>') +
      '<div class="sitenav-item">' +
      '<button type="button" class="sitenav-btn" aria-expanded="false" aria-haspopup="true">Tools<span class="sitenav-caret">▾</span></button>' +
      '<div class="sitenav-menu sitenav-menu--tools">' + toolsHtml() + '</div>' +
      '</div>' +
      '<div class="sitenav-item">' +
      '<button type="button" class="sitenav-btn" aria-expanded="false" aria-haspopup="true">Posts<span class="sitenav-caret">▾</span></button>' +
      '<div class="sitenav-menu">' + postsHtml() + '</div>' +
      '</div>' +
      '<span class="sitenav-spacer"></span>' +
      '<a class="nav-pill" href="/members/">Memberships</a>' +
      '</div>';
    header.insertAdjacentElement('afterend', bar);

    var items = bar.querySelectorAll('.sitenav-item');
    var groups = bar.querySelectorAll('.menu-group');
    function closeAll() {
      items.forEach(function (item) {
        item.classList.remove('open');
        item.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'false');
        item.querySelectorAll('.menu-group.sub-open').forEach(function (g) { g.classList.remove('sub-open'); });
      });
      groups.forEach(function (g) {
        g.classList.remove('sub-hover');
        clearTimeout(g._openT);
        clearTimeout(g._closeT);
      });
    }
    items.forEach(function (item) {
      var btn = item.querySelector('.sitenav-btn');
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var wasOpen = item.classList.contains('open');
        closeAll();
        if (!wasOpen) {
          item.classList.add('open');
          btn.setAttribute('aria-expanded', 'true');
        }
      });
    });
    if (window.matchMedia && window.matchMedia('(hover: hover)').matches) {
      items.forEach(function (item) {
        var closeTimer = null;
        item.addEventListener('mouseenter', function () {
          clearTimeout(closeTimer);
          closeAll();
          item.classList.add('open');
          item.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'true');
        });
        item.addEventListener('mouseleave', function () {
          closeTimer = setTimeout(function () {
            item.classList.remove('open');
            item.querySelector('.sitenav-btn').setAttribute('aria-expanded', 'false');
          }, 180);
        });
      });
      /* Submenu flyouts: intent timers instead of raw :hover. A short open
         delay keeps a diagonal pass over a neighboring row from stealing the
         flyout; a longer close delay (plus the ::before bridge) gives the
         pointer time to travel from the row into the flyout. The flyout is a
         DOM child of its .menu-group, so re-entering it cancels the close. */
      groups.forEach(function (g) {
        g.addEventListener('mouseenter', function () {
          clearTimeout(g._closeT);
          clearTimeout(g._openT);
          g._openT = setTimeout(function () {
            groups.forEach(function (o) {
              if (o !== g) { o.classList.remove('sub-hover'); clearTimeout(o._openT); }
            });
            g.classList.add('sub-hover');
          }, 100);
        });
        g.addEventListener('mouseleave', function () {
          clearTimeout(g._openT);
          g._closeT = setTimeout(function () {
            g.classList.remove('sub-hover');
          }, 300);
        });
      });
    }
    bar.querySelectorAll('.sub-toggle').forEach(function (tog) {
      tog.addEventListener('click', function (ev) {
        ev.stopPropagation();
        tog.parentNode.parentNode.classList.toggle('sub-open');
      });
    });
    document.addEventListener('click', closeAll);
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') closeAll();
    });
  }

  var footerNav = document.querySelector('footer .footer-links');
  if (footerNav && !footerNav.querySelector('a[href="/members/"]')) {
    var memLink = document.createElement('a');
    memLink.href = '/members/';
    memLink.textContent = 'Memberships';
    var xLink = document.createElement('a');
    xLink.href = 'https://x.com/TalR24';
    xLink.target = '_blank';
    xLink.rel = 'noopener';
    xLink.textContent = 'X';
    var plainLinks = footerNav.querySelectorAll('a:not(.footer-support)');
    var lastPlain = plainLinks.length ? plainLinks[plainLinks.length - 1] : null;
    if (lastPlain) {
      var anchor = lastPlain.nextSibling;
      footerNav.insertBefore(memLink, anchor);
      footerNav.insertBefore(xLink, anchor);
    } else {
      footerNav.appendChild(memLink);
      footerNav.appendChild(xLink);
    }
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
