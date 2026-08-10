/* ==========================================================================
   NYCuriosity chart system — shared behaviour
   --------------------------------------------------------------------------
   Pairs with /assets/chart.css. Load with:
     <script defer src="/assets/chart.js"></script>

   Provides:
     - the NYCuriosity wordmark, injected into every .c-foot
     - PNG capture of a .chart-card (canvas-safe)
     - the embed modal
     - the canonical number formatters
     - the sequential and diverging palettes as arrays

   Everything lives inside an IIFE. Only the handlers that inline onclick
   attributes need are attached to window, and none of them shadow a
   restricted window global (top, name, length, origin, status, parent...),
   which silently kills an entire script when it happens at top level.
   ========================================================================== */

(function () {
  'use strict';

  /* ---- palettes -------------------------------------------------------- */

  var SEQ = ['#1e3a8a', '#1e40af', '#1d4ed8', '#2563eb', '#3b82f6', '#519bf8',
             '#60a5fa', '#7db3fb', '#93c5fd', '#aed4fe', '#bfdbfe'];
  var DIVERGING = ['#b91c1c', '#dc2626', '#fca5a5', '#f3f4f6', '#93c5fd', '#3b82f6', '#1d4ed8'];
  var CATEGORICAL = ['#2563eb', '#c2410c', '#6b7280', '#16a34a'];
  var RESIDUAL = '#6b7280';
  var SEQ_INK_DARK = '#1e3a8a';

  /* Sample n evenly spaced colours from the sequential ramp, darkest first. */
  function seqRamp(n) {
    if (n <= 1) return [SEQ[3]];
    var out = [];
    for (var i = 0; i < n; i++) {
      out.push(SEQ[Math.round(i * (SEQ.length - 1) / (n - 1))]);
    }
    return out;
  }

  /* White reads on the dark half of the ramp only. Past the midpoint the
     contrast drops below 3:1, so the label flips to navy. */
  function seqLabelInk(index, n) {
    var pos = n <= 1 ? 0 : index / (n - 1);
    return pos <= 0.42 ? '#ffffff' : SEQ_INK_DARK;
  }

  /* ---- number formatting ----------------------------------------------- */

  function fmtCompactUSD(v) {
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (v >= 1e3) return '$' + Math.round(v / 1e3) + 'K';
    return '$' + v.toLocaleString('en-US');
  }
  function fmtUSD(v) { return '$' + Math.round(v).toLocaleString('en-US'); }
  function fmtNum(v) { return v.toLocaleString('en-US'); }
  function fmtPct(v, dp) { return v.toFixed(dp === undefined ? 1 : dp) + '%'; }

  /* ---- wordmark -------------------------------------------------------- */

  function markup() {
    return '<span class="c-mark-bars" aria-hidden="true">' +
             '<i style="height:6px"></i><i style="height:10px"></i><i style="height:13px"></i>' +
           '</span><span class="c-mark-wm">NYCURIOSITY</span>';
  }

  /* Every chart footer carries the wordmark, so an exported PNG stays
     identifiable once it is off the site. */
  function injectMarks(root) {
    var feet = (root || document).querySelectorAll('.c-foot');
    for (var i = 0; i < feet.length; i++) {
      if (feet[i].querySelector('.c-mark')) continue;
      var mark = document.createElement('div');
      mark.className = 'c-mark';
      mark.setAttribute('aria-label', 'NYCuriosity');
      mark.innerHTML = markup();
      feet[i].appendChild(mark);
    }
  }

  /* ---- bar rows -------------------------------------------------------- */

  /* A value label sits inside its bar unless the bar is too short to hold it,
     in which case it moves outside and switches to dark ink. */
  function placeBarValues(root) {
    var rows = (root || document).querySelectorAll('.c-bar-row');
    for (var i = 0; i < rows.length; i++) {
      var fill = rows[i].querySelector('.c-bar-fill');
      var inval = rows[i].querySelector('.c-bar-inval');
      if (!fill || !inval) continue;
      if (fill.getBoundingClientRect().width < inval.scrollWidth + 22) {
        inval.style.color = SEQ_INK_DARK;
        inval.style.paddingRight = '0';
        inval.style.paddingLeft = '8px';
        fill.style.justifyContent = 'flex-start';
        fill.style.overflow = 'visible';
      }
    }
  }

  /* ---- PNG capture ----------------------------------------------------- */

  /* A cloned <canvas> exports blank, so each one is swapped for a static
     snapshot for the duration of the capture and restored afterwards. */
  function captureNode(node, background) {
    var canvases = node.querySelectorAll('canvas');
    var swapped = [];
    for (var i = 0; i < canvases.length; i++) {
      var c = canvases[i];
      try {
        var img = new Image();
        img.src = c.toDataURL('image/png');
        img.width = c.clientWidth;
        img.height = c.clientHeight;
        img.style.width = c.clientWidth + 'px';
        img.style.height = c.clientHeight + 'px';
        c.parentNode.insertBefore(img, c);
        c.style.display = 'none';
        swapped.push({ canvas: c, img: img });
      } catch (e) { /* tainted canvas: fall through and capture as-is */ }
    }
    return window.htmlToImage
      .toPng(node, { backgroundColor: background || '#ffffff', pixelRatio: 2 })
      .then(function (url) { restore(swapped); return url; })
      .catch(function (err) { restore(swapped); throw err; });
  }

  function restore(swapped) {
    for (var i = 0; i < swapped.length; i++) {
      swapped[i].canvas.style.display = '';
      if (swapped[i].img.parentNode) swapped[i].img.parentNode.removeChild(swapped[i].img);
    }
  }

  /* Captures the .chart-card the button belongs to. Falls back to the first
     card on the page, then to the legacy #chart-box, so a half-migrated page
     keeps working. */
  function resolveCard(btn) {
    if (btn) {
      var scope = btn.closest ? btn.closest('.c-actions') : null;
      if (scope && scope.dataset && scope.dataset.target) {
        var byId = document.getElementById(scope.dataset.target);
        if (byId) return byId;
      }
      if (scope && scope.nextElementSibling &&
          scope.nextElementSibling.classList.contains('chart-card')) {
        return scope.nextElementSibling;
      }
    }
    return document.querySelector('.chart-card') || document.getElementById('chart-box');
  }

  function downloadChart(btn, filename) {
    var card = resolveCard(btn);
    if (!card) return;
    var slug = filename || card.getAttribute('data-slug') || 'nycuriosity-chart';
    if (slug.slice(-4) !== '.png') slug += '.png';
    var orig = btn ? btn.innerHTML : '';
    if (btn) { btn.innerHTML = '⏳ Capturing…'; btn.disabled = true; }
    captureNode(card, '#ffffff')
      .then(function (url) {
        var a = document.createElement('a');
        a.download = slug;
        a.href = url;
        a.click();
      })
      .catch(function (err) { console.error('Chart capture failed:', err); })
      .then(function () { if (btn) { btn.innerHTML = orig; btn.disabled = false; } });
  }

  /* ---- embed modal ----------------------------------------------------- */

  function embedHeight() {
    var card = document.querySelector('.chart-card') || document.getElementById('chart-box');
    if (!card) return 720;
    /* Card height plus the hero and footnotes the iframe also shows, rounded
       up so the embed never needs an inner scrollbar. */
    return Math.ceil((card.getBoundingClientRect().height + 420) / 20) * 20;
  }

  function showEmbed() {
    var box = document.getElementById('embedModal');
    var field = document.getElementById('embedCode');
    if (!box || !field) return;
    var url = window.location.origin + window.location.pathname;
    field.value = '<iframe src="' + url + '" width="900" height="' + embedHeight() +
      '" frameborder="0" style="border:1px solid #e5e7eb; border-radius:8px;" loading="lazy"></iframe>';
    box.style.display = 'flex';
  }
  function closeEmbed() {
    var box = document.getElementById('embedModal');
    if (box) box.style.display = 'none';
  }
  /* Pages label this button differently ("Copy code", "Copy"), so restore
     whatever the button actually said rather than assuming. Accepts the
     clicked element so a page with its own button class still gets the
     confirmation state. */
  function copyEmbed(btn) {
    var field = document.getElementById('embedCode');
    if (!field) return;
    field.select();
    var target = (btn && btn.tagName === 'BUTTON') ? btn
      : document.querySelector('.embed-copy-btn') || document.getElementById('copyBtn');
    var label = target ? target.textContent : null;
    navigator.clipboard.writeText(field.value).then(function () {
      if (!target) return;
      target.textContent = '✓ Copied!';
      setTimeout(function () { target.textContent = label; }, 2000);
    });
  }

  /* ---- Chart.js defaults ----------------------------------------------- */

  function applyChartDefaults() {
    if (!window.Chart) return;
    var d = window.Chart.defaults;
    d.font.family = "'Inter', system-ui, sans-serif";
    d.font.size = 12;
    d.color = '#374151';
    d.borderColor = '#e5e7eb';
    d.plugins.legend.position = 'bottom';
    d.plugins.legend.labels.boxWidth = 12;
    d.plugins.legend.labels.font = { family: "'Inter', system-ui, sans-serif", size: 12 };
    d.plugins.tooltip.backgroundColor = '#111827';
    d.plugins.tooltip.titleFont = { family: "'Roboto Mono', monospace", size: 12, weight: '700' };
    d.plugins.tooltip.bodyFont = { family: "'Roboto Mono', monospace", size: 11 };
    d.plugins.tooltip.padding = 12;
    d.plugins.tooltip.cornerRadius = 8;
    d.datasets.bar.borderRadius = 2;
    d.datasets.bar.borderSkipped = false;
    d.elements.line.tension = 0;
    d.elements.line.borderWidth = 2.5;
    d.elements.point.radius = 3.5;
    d.scale.grid.color = '#e5e7eb';
    d.scale.ticks.font = { family: "'Roboto Mono', monospace", size: 11 };
    d.scale.ticks.color = '#6b7280';
  }

  /* ---- boot ------------------------------------------------------------ */

  function boot() {
    injectMarks(document);
    applyChartDefaults();
    /* Bars animate in, so measure after the transition has settled. */
    setTimeout(function () { placeBarValues(document); }, 1100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  /* ---- public surface -------------------------------------------------- */

  window.NYCChart = {
    SEQ: SEQ,
    DIVERGING: DIVERGING,
    CATEGORICAL: CATEGORICAL,
    RESIDUAL: RESIDUAL,
    seqRamp: seqRamp,
    seqLabelInk: seqLabelInk,
    fmtUSD: fmtUSD,
    fmtCompactUSD: fmtCompactUSD,
    fmtNum: fmtNum,
    fmtPct: fmtPct,
    captureNode: captureNode,
    injectMarks: injectMarks,
    placeBarValues: placeBarValues
  };

  /* Inline onclick handlers on existing pages call these by bare name. */
  window.downloadChart = downloadChart;
  window.showEmbed = showEmbed;
  window.closeEmbed = closeEmbed;
  window.copyEmbed = copyEmbed;
})();
