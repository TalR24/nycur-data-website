/* Site-wide chrome: pill-style nav bar with two-level Tools / category-grouped
   Posts dropdowns under the header + "More from NYCuriosity Data" related-work
   block above the footer. Included on every live page (incl. the homepage)
   except the State Capacity Ecosystem section, /members/, and redirect stubs.
   Related work is curated in /assets/related_work.json (path-prefix keys).
   When a tool or post hub ships: add it to TOOLS_MENU (with sub list) or the
   right POSTS_MENU category (newest first, max 2 shown). Sub lists cap at 5
   items (override with max: N on the entry); the flyout always ends with a See-all link to the hub. */
(function () {
  var path = location.pathname;
  var isHome = path === '/' || path === '/index.html';

  var TOOLS_MENU = [
    { label: 'NYC Council Legislation Trackers', href: '/civic_reference/nyc_council_legislation_trackers/', sub: [
      { label: 'Fiscal Impacts', href: '/civic_reference/nyc_council_fiscal_impacts_tracker/overview/' },
      { label: 'Obligations', href: '/civic_reference/legislation_implementation_tracker/' },
      { label: 'Powers', href: '/civic_reference/legislation_implementation_tracker/powers/' },
      { label: 'Council Members', href: '/civic_reference/nyc_council_legislation_trackers/council-members/' },
      { label: 'Agencies', href: '/civic_reference/nyc_council_legislation_trackers/agencies/' }
    ]},
    { label: 'NYS Legislation Trackers', href: '/civic_reference/nys_legislation_trackers/', max: 7, sub: [
      { label: 'Overview', href: '/civic_reference/nys_legislation_trackers/' },
      { label: 'Bill Explorer', href: '/civic_reference/nys_legislation_trackers/bills/' },
      { label: 'Duties Tracker', href: '/civic_reference/nys_legislation_trackers/duties/' },
      { label: 'Powers Tracker', href: '/civic_reference/nys_legislation_trackers/powers/' },
      { label: 'Agencies', href: '/civic_reference/nys_legislation_trackers/agencies/' },
      { label: 'Legislators', href: '/civic_reference/nys_legislation_trackers/legislators/' },
      { label: 'Alerts', href: '/civic_reference/nys_legislation_trackers/alerts/' }
    ]},
    { label: 'Community Board Tools', href: '/cb-tools/', sub: [
      { label: 'Member Tracker', href: '/cb-tools/member-tracker/' },
      { label: 'Member Guide', href: '/civic_reference/cb_member_guide/' },
      { label: 'Block Party archive', href: '/cb-tools/block-party/' },
      { label: 'Robert’s Rules helper', href: '/cb-tools/roberts-rules-helper/' },
      { label: 'AI meeting review', href: '/cb-tools/meeting-review/' }
    ]}
  ];


  var POSTS_MENU = [
    { cat: 'Transit & Streets', topic: 'transit', items: [
      { label: 'Livable streets beyond Manhattan', href: '/nycuriosity_substack_posts/livable_streets_cuf/' },
      { label: 'Two Years of G Train Weekend Shutdowns', href: '/nycuriosity_substack_posts/g_train_weekend_shutdowns/' },
      { label: 'West 4th St Station Deep Dive', href: '/nycuriosity_substack_posts/west_4th_st_station/' },
      { label: 'New York Needs to Grow', href: '/nycuriosity_substack_posts/nyc_building_strategies/' }
    ]},
    { cat: 'Community Boards', topic: 'cb', items: [
      { label: 'What 27 community boards vote on', href: '/nycuriosity_substack_posts/block_party_updates_2026/' },
      { label: 'Suggestions to Improve NYC Community Boards', href: '/nycuriosity_substack_posts/community_board_suggestions/' },
      { label: 'What Has MCB3 Focused On Over Time?', href: '/nycuriosity_substack_posts/mcb3_history_analysis/' }
    ]},
    { cat: 'Budget & Policy', topic: 'budget', items: [
      { label: 'Party competition in New York City', href: '/nycuriosity_substack_posts/robust_opposition/' },
      { label: 'Fair Housing Growth Strategy targets', href: '/nycuriosity_substack_posts/fair_housing_growth_strategy/' },
      { label: 'Park restroom costs', href: '/nycuriosity_substack_posts/public_restrooms/' },
      { label: 'Labor Costs and the 2026 Bargaining Round', href: '/nycuriosity_substack_posts/public_sector_unions_2026/' },
      { label: 'What the Council Asks of NYC Agencies', href: '/nycuriosity_substack_posts/council_obligations/' },
      { label: 'Medicaid’s Check Register Is Public', href: '/nycuriosity_substack_posts/medicaid_provider_spending/' }
    ]},
    { cat: 'Government & Technology', topic: 'govtech', items: [
      { label: 'Community data pipeline', href: '/nycuriosity_substack_posts/vital_city_community_data/' },
      { label: 'Duties, Powers and Staffing in the Legislation Trackers Update', href: '/nycuriosity_substack_posts/legislation_trackers_update/' },
      { label: 'What Mamdani’s Efficiency Commission Put on the Ballot', href: '/nycuriosity_substack_posts/coge_report/' },
      { label: 'State Capacity Has a New Toolkit', href: '/nycuriosity_substack_posts/state_capacity_ai/' }
    ]}
  ];

  var styleEl = document.createElement('style');
  styleEl.textContent =
    '.sitenav{background:#170C03;border-top:1px solid #2E1C0C;border-bottom:1px solid #2E1C0C;padding:0 clamp(20px,5vw,48px);}' +
    '.sitenav-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;gap:10px;min-height:52px;flex-wrap:wrap;padding:8px 0;}' +
    '.sitenav .nav-pill,.sitenav-btn{font-family: var(--b-sans);font-size:0.8rem;font-weight:600;color:#E7DDCE;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.22);border-radius:20px;padding:7px 16px;text-decoration:none;white-space:nowrap;cursor:pointer;transition:all 0.15s;display:inline-flex;align-items:center;gap:6px;}' +
    '.sitenav .nav-pill:hover,.sitenav-btn:hover,.sitenav-item.open .sitenav-btn{background:#C84609;border-color:#C84609;color:#fff;}' +
    '.sitenav-item{position:relative;}' +
    '.sitenav-caret{font-size:0.6rem;}' +
    '.sitenav-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;z-index:200;background:#ffffff;border:1px solid #E7DDCE;border-radius:12px;box-shadow:0 10px 28px rgba(26,18,8,0.18);padding:10px;min-width:310px;max-height:72vh;overflow-y:auto;}' +
    '.sitenav-menu--tools{max-height:none;overflow:visible;}' +
    '.sitenav-item.open .sitenav-menu{display:block;}' +
    '.sitenav-menu a{display:block;padding:7px 10px;border-radius:6px;color:#4A3B2C;font-family: var(--b-sans);font-size:0.74rem;font-weight:600;text-decoration:none;white-space:normal;line-height:1.4;}' +
    '.sitenav-menu a:hover{background:#FAF6F1;color:#C84609;}' +
    '.menu-cat{font-family: var(--b-sans);font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing: normal;color:#A44D00;padding:10px 10px 4px;}' +
    '.menu-cat:first-child{padding-top:4px;}' +
    '.sitenav-menu .menu-seeall{color:#C84609;font-size:0.7rem;padding-top:3px;padding-bottom:9px;border-bottom:1px solid #F2EBE1;border-radius:0;margin-bottom:2px;}' +
    '.sitenav-menu .menu-all{color:#C84609;border-top:1px solid #E7DDCE;border-radius:0 0 8px 8px;margin-top:6px;padding-top:10px;}' +
    '.menu-group{position:relative;}' +
    '.menu-row{display:flex;align-items:center;gap:2px;}' +
    '.menu-row .menu-link{flex:1;}' +
    '.sub-toggle{flex-shrink:0;background:none;border:none;color:#9A8B7A;font-size:0.7rem;padding:6px 8px;cursor:pointer;border-radius:6px;}' +
    '.sub-toggle:hover{background:#FAF6F1;color:#C84609;}' +
    '.sitenav-sub{display:none;position:absolute;left:100%;top:-10px;margin-left:8px;z-index:210;background:#ffffff;border:1px solid #E7DDCE;border-radius:12px;box-shadow:0 10px 28px rgba(26,18,8,0.18);padding:8px;min-width:240px;}' +
    /* Invisible bridge over the 8px gap (and a little above/below) so the
       pointer can cross from the menu row into the flyout without the group
       losing hover. Works with the JS grace timers below. */
    '.sitenav-sub::before{content:\'\';position:absolute;top:-10px;bottom:-10px;left:-18px;width:18px;}' +
    '.menu-group.sub-hover > .sitenav-sub{display:block;}' +
    '.menu-group.sub-open > .sitenav-sub{display:block;position:static;margin:2px 0 6px 14px;border:none;box-shadow:none;border-left:2px solid #E7DDCE;border-radius:0;padding:0 0 0 8px;min-width:0;}' +
    '.sitenav-spacer{flex:1;}' +
    /* Subpage header layout (moved here from brand.css, which holds tokens only).
       Back link and page title are never cut off: the back link keeps its full
       width, the title wraps to at most two lines. On phones the back link may
       wrap too. About and Substack hide only below the width where the longest
       real back link and title stop fitting beside them. */
    'header .header-inner .brand{display:flex;align-items:center;flex-shrink:0;text-decoration:none;}' +
    'header .header-inner:has(.back-link){height:auto;min-height:56px;padding:8px 0;min-width:0;flex-wrap:wrap;row-gap:4px;}' +
    'header .header-inner .back-link{display:block;flex:0 1 auto;max-width:100%;overflow:visible;text-overflow:clip;white-space:normal;overflow-wrap:anywhere;font-family:var(--b-sans);}' +
    'header .header-inner .back-link svg{vertical-align:-2px;}' +
    'header .header-inner .header-actions{flex-shrink:0;}' +
    'header .header-inner .site-header-title{font-family:var(--b-display);flex:1 1 12ch;min-width:min(12ch,100%);white-space:normal;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;line-clamp:3;}' +
    /* Nov 11 2026: on subpages, About and Substack collapse to their icons below 1220px instead of vanishing
       (the label stays in the DOM for screen readers and becomes a tooltip); they hide only on phones. */
    '@media (max-width:1220px){header .header-inner:has(.back-link) .header-actions .header-link{display:flex;font-size:0;gap:0;padding:7px;}}' +
    '@media (max-width:560px){header .header-inner:has(.back-link) .header-actions .header-link{display:none;}}' +
    '@media (max-width:900px){header .header-inner:has(.back-link) .header-divider{display:none;}}' +
    '@media (max-width:560px){' +
      'header .header-inner:has(.back-link) .brand{flex:0 1 calc(100% - 48px);}' +
      'header .header-inner:has(.back-link) .site-header-title{flex:1 1 55%;-webkit-line-clamp:2;line-clamp:2;}' +
    '}' +
    '@media (max-width:640px){code{overflow-wrap:anywhere;}}' +
    /* Phone navigation (Nov 10 2026): fewer stacked rows before the content. The Home pill is hidden because
       the wordmark above it links home; the remaining pills fit one row; and the page's own pill rows (the
       'Visuals in this post' and 'Views in this tool' rows and the tracker switcher) become one line that
       scrolls sideways with a fade at the right edge instead of wrapping to three or four rows. */
    '@media (max-width:640px){' +
      '.sitenav .nav-pill[href="/"]{display:none;}' +
      '.sitenav{padding:0 12px;}' +
      '.sitenav-inner{gap:5px;min-height:46px;padding:6px 0;flex-wrap:nowrap;}' +
      '.sitenav .nav-pill,.sitenav-btn{font-size:0.7rem;padding:7px 9px;}' +
            '.sitenav-spacer{display:none;}' +
      '.pill-nav,.chart-nav,.trk-switch{flex-wrap:nowrap !important;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 32px),transparent);mask-image:linear-gradient(to right,#000 calc(100% - 32px),transparent);}' +
      '.pill-nav::-webkit-scrollbar,.chart-nav::-webkit-scrollbar,.trk-switch::-webkit-scrollbar{display:none;}' +
      '.pill-nav > *,.chart-nav > *,.trk-switch > *{flex:0 0 auto;white-space:nowrap;}' +
      '.pill-nav::after,.chart-nav::after,.trk-switch::after{content:"";flex:0 0 28px;}' +
    '}' +
    '@media (max-width:370px){.sitenav-inner{flex-wrap:wrap;}}' +
    /* Related-work cards wrap or scroll inside their container at any width. */
    '.relwork,.relwork-inner,.relwork-grid{min-width:0;max-width:100%;}' +
    '.relwork-card{min-width:0;max-width:100%;overflow-wrap:anywhere;}' +
    /* h1 is always the display face (the cb-tools hubs set none). */
    'h1{font-family:var(--b-display);}' +
    /* Faint text: --b-ink-4 is decorative only (3.31:1 on white), so every text
       use of the faint token resolves to --b-ink-3 (6.1:1 on cream). Literal
       #9A8B7A text rules that pages set directly are listed here. */
    ':root{--text-faint:var(--b-ink-3);}' +
    '.bar-label .sublabel,.footnotes h3,.filter-panel-title,.c-foot-text span,footer .footer-links a,.view-card-stat,.col-label,.chart-note,.hub-card-stat,.hero-updated,.proto-section-label,.proto-stat,.category-name,.cy-empty{color:var(--b-ink-3);}' +
    '.relwork{padding:8px clamp(20px,5vw,48px) 44px;}' +
    '.relwork-inner{max-width:900px;margin:0 auto;}' +
    '.relwork-label{font-family: var(--b-sans);font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing: normal;color:#A44D00;margin-bottom:14px;}' +
    // always one row (Tal, Sep 24 2026): cards share the width; 4+ cards get
    // tighter type; on phones the single row scrolls sideways instead of wrapping
    '.relwork-grid{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:14px;}' +
    '.relwork-grid.dense{gap:10px;}' +
    '.relwork-grid.dense .relwork-card{padding:13px 14px;}' +
    '.relwork-grid.dense .relwork-title{font-size:0.78rem;}' +
    '@media (max-width:640px){.relwork-grid,.relwork-grid.dense{grid-auto-columns:minmax(210px,78%);overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:8px;-webkit-overflow-scrolling:touch;}.relwork-card{scroll-snap-align:start;}}' +
    '.relwork-card{background:#fff;border:1px solid #E7DDCE;border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:6px;text-decoration:none;box-shadow:0 1px 3px rgba(26,18,8,0.08);transition:border-color 0.2s,box-shadow 0.2s,transform 0.15s;}' +
    '.relwork-card:hover{border-color:#C84609;transform:translateY(-2px);box-shadow:0 4px 16px rgba(207,75,12,0.10);}' +
    '.relwork-tag{font-family: var(--b-sans);font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing: normal;color:#A44D00;}' +
    '.relwork-title{font-family: var(--b-display);font-size:0.85rem;font-weight:700;color:#1A1208;line-height:1.35;}' +
    '.relwork-cta{font-family: var(--b-sans);font-size:0.72rem;font-weight:600;color:#C84609;margin-top:auto;padding-top:4px;}' +
    /* The footer nav is a flex row with no wrap in every page's local CSS, so
       on a 360px screen it measures 490px and pushes the whole page into
       horizontal scroll. Patched here because site.js is the one stylesheet
       shared across the site. Pages without site.js (SCE, /members/, redirect
       stubs) still need this locally. */
    '.footer-links{flex-wrap:wrap;}' +
    /* Wider desktop layout (Tal, Sep 26 2026): on screens 1100px and up the
       content column uses 1240px and intros 920px instead of a narrow 900/680.
       Below 1100px every page keeps its own widths, so phones are unchanged.
       !important because pages set these widths in their own <style>. */
    /* Text contrast (Nov 2026): --b-ink-4 is decorative only (3.07:1 on cream),
       so label and note text uses --b-ink-3 (5.4:1). Link and last-crumb colours
       keep their own, more specific rules. */
    '.breadcrumb,.footer-copy,.pill-label,.section-label,.section-label-row,.map-hint{color:var(--b-ink-3);}' +
    /* Tap targets: footer and breadcrumb links get a 24px minimum hit area. */
    '.footer-links a:not(.footer-support),.breadcrumb a{display:inline-block;min-height:24px;line-height:24px;}' +
    '@media (min-width:1100px){' +
      '.header-inner,.hero-inner,.main-inner,.footer-inner,.stat-row-inner,.charts-inner,' +
      '.sitenav-inner,.relwork-inner,.trk-studio-inner,.projects-inner,.band-inner,.charts-nav-inner,.table-inner{max-width:1240px !important;}' +
      '.hero p{max-width:920px !important;}' +
    '}';
  document.head.appendChild(styleEl);

  function toolsHtml() {
    return TOOLS_MENU.map(function (t) {
      if (!t.sub || !t.sub.length) {
        return '<a class="menu-link" href="' + t.href + '">' + t.label + '</a>';
      }
      var shown = t.sub.slice(0, t.max || 5);
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
      '<a class="nav-pill" href="https://talroded.nycuriosity.com/services/">NYCuriosity Studio</a>' +
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
    var canHover = !!(window.matchMedia && window.matchMedia('(hover: hover)').matches);
    items.forEach(function (item) {
      var btn = item.querySelector('.sitenav-btn');
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        var wasOpen = item.classList.contains('open');
        /* Hover-capable pointers already opened the menu on mouseenter, so a
           mouse click keeps it open (outside click or Escape closes it).
           Keyboard activation (ev.detail 0) and touch still toggle. */
        if (wasOpen && canHover && ev.detail > 0) return;
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
  // NYCuriosity Studio (paid services) sits beside Memberships (Tal, Sep 24 2026)
  var STUDIO_URL = 'https://talroded.nycuriosity.com/services/';
  if (footerNav && !footerNav.querySelector('a[href="' + STUDIO_URL + '"]')) {
    var studioLink = document.createElement('a');
    studioLink.href = STUDIO_URL;
    studioLink.textContent = 'NYCuriosity Studio';
    var iconSlot = footerNav.querySelector('a[title]');
    if (iconSlot) footerNav.insertBefore(studioLink, iconSlot); else footerNav.appendChild(studioLink);
  }
  if (footerNav && !footerNav.querySelector('a[href="/members/"]')) {
    var memLink = document.createElement('a');
    memLink.href = '/members/';
    memLink.textContent = 'Memberships';
    // X lives in the static social icon row (Aug 2026); do not inject it here.
    var firstIcon = footerNav.querySelector('a[title]');
    if (firstIcon) {
      footerNav.insertBefore(memLink, firstIcon);
    } else {
      footerNav.appendChild(memLink);
    }
  }

  // Phone navigation: bring the active pill into view in the single-line pill rows.
  function revealActivePills() {
    var rows = document.querySelectorAll('.pill-nav, .chart-nav, .trk-switch');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i], act = row.querySelector('a.active, a[aria-current="page"]');
      if (act && row.scrollWidth > row.clientWidth) row.scrollLeft = Math.max(0, act.offsetLeft - row.offsetLeft - 48);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', revealActivePills);
  else revealActivePills();
  window.addEventListener('load', revealActivePills);
  function titleHeaderLinks() {
    document.querySelectorAll('header .header-actions .header-link').forEach(function (a) {
      if (!a.title) a.title = a.textContent.trim();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', titleHeaderLinks);
  else titleHeaderLinks();
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
        '<div class="relwork-grid' + (items.length >= 4 ? ' dense' : '') + '">' +
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
