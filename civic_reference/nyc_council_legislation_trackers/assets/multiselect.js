/*
 * MSFilter — shared multi-select filter dropdown for the NYC Council
 * Legislation Trackers (used by both the obligations and fiscal pages).
 *
 * Usage:
 *   var f = new MSFilter('mountId', {
 *     label: 'Agency',
 *     options: [{v: 'DOT', l: 'Department of Transportation (DOT)'}, ...],
 *     sort: 'alpha' | 'none',       // 'none' keeps the given order
 *     allLabel: 'All agencies',
 *     onChange: function () { ... }
 *   });
 *   f.selected()  -> null when every box is checked (no filtering),
 *                    otherwise a Set of checked values (possibly empty).
 *   f.reset()     -> re-check everything (no filtering) without firing onChange.
 *
 * All boxes start checked. Each panel has Select all / Select none links.
 * Injects its own CSS once. No dependencies.
 */
(function (global) {
  'use strict';

  var CSS = ''
    + '.msf{position:relative;display:flex;flex-direction:column;gap:5px;}'
    + '.msf-label{font-family:"Roboto Mono",monospace;font-size:0.62rem;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:#6b7280;}'
    + '.msf-btn{width:100%;text-align:left;padding:8px 26px 8px 10px;border:1px solid #e5e7eb;border-radius:7px;font-family:"Roboto Mono",monospace;font-size:0.75rem;background:#f8faff;color:#374151;cursor:pointer;position:relative;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}'
    + '.msf-btn::after{content:"\\25BE";position:absolute;right:9px;top:50%;transform:translateY(-50%);color:#9ca3af;font-size:0.7rem;}'
    + '.msf-btn:focus{outline:2px solid #bfdbfe;border-color:#2563eb;}'
    + '.msf-btn.msf-active{border-color:#2563eb;color:#2563eb;font-weight:600;}'
    + '.msf-panel{display:none;position:absolute;z-index:40;top:100%;left:0;margin-top:4px;min-width:100%;width:max-content;max-width:290px;background:#fff;border:1.5px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 24px rgba(17,24,39,0.14);}'
    + '.msf.open .msf-panel{display:block;}'
    + '.msf-actions{display:flex;gap:12px;padding:8px 12px;border-bottom:1px solid #e5e7eb;}'
    + '.msf-actions a{font-family:"Roboto Mono",monospace;font-size:0.68rem;font-weight:600;color:#2563eb;cursor:pointer;text-decoration:none;}'
    + '.msf-actions a:hover{text-decoration:underline;}'
    + '.msf-list{max-height:240px;overflow-y:auto;padding:6px 8px;}'
    + '.msf-list label{display:flex;align-items:baseline;gap:8px;padding:4px 4px;font-family:"Inter",sans-serif;font-size:0.8rem;color:#374151;cursor:pointer;border-radius:5px;line-height:1.35;}'
    + '.msf-list label:hover{background:#eff6ff;color:#2563eb;}'
    + '.msf-list input{accent-color:#2563eb;flex-shrink:0;position:relative;top:1px;}';

  var cssInjected = false;

  function MSFilter(mountId, cfg) {
    if (!cssInjected) {
      var st = document.createElement('style');
      st.textContent = CSS;
      document.head.appendChild(st);
      cssInjected = true;
    }
    this.cfg = cfg;
    this.options = cfg.options.slice();
    if (cfg.sort === 'alpha') {
      this.options.sort(function (a, b) {
        return String(a.l).localeCompare(String(b.l), undefined, {sensitivity: 'base'});
      });
    }
    this.checked = {};
    var self = this;
    this.options.forEach(function (o) { self.checked[o.v] = true; });

    var mount = document.getElementById(mountId);
    mount.classList.add('msf');
    mount.innerHTML = ''
      + '<span class="msf-label">' + esc(cfg.label) + '</span>'
      + '<button type="button" class="msf-btn"></button>'
      + '<div class="msf-panel">'
      + '<div class="msf-actions"><a data-act="all">Select all</a><a data-act="none">Select none</a></div>'
      + '<div class="msf-list">'
      + this.options.map(function (o) {
          return '<label><input type="checkbox" checked value="' + esc(o.v) + '"><span>' + esc(o.l) + '</span></label>';
        }).join('')
      + '</div></div>';

    this.mount = mount;
    this.btn = mount.querySelector('.msf-btn');
    this.updateBtn();

    this.btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var wasOpen = mount.classList.contains('open');
      document.querySelectorAll('.msf.open').forEach(function (m) { m.classList.remove('open'); });
      if (!wasOpen) mount.classList.add('open');
    });
    mount.querySelector('.msf-panel').addEventListener('click', function (e) {
      e.stopPropagation();
    });
    mount.querySelectorAll('.msf-actions a').forEach(function (a) {
      a.addEventListener('click', function () {
        var on = a.getAttribute('data-act') === 'all';
        mount.querySelectorAll('.msf-list input').forEach(function (i) {
          i.checked = on;
          self.checked[i.value] = on;
        });
        self.updateBtn();
        cfg.onChange();
      });
    });
    mount.querySelectorAll('.msf-list input').forEach(function (i) {
      i.addEventListener('change', function () {
        self.checked[i.value] = i.checked;
        self.updateBtn();
        cfg.onChange();
      });
    });
    if (!MSFilter._outside) {
      MSFilter._outside = true;
      document.addEventListener('click', function () {
        document.querySelectorAll('.msf.open').forEach(function (m) { m.classList.remove('open'); });
      });
    }
  }

  MSFilter.prototype.count = function () {
    var n = 0, self = this;
    this.options.forEach(function (o) { if (self.checked[o.v]) n++; });
    return n;
  };

  MSFilter.prototype.updateBtn = function () {
    var n = this.count(), total = this.options.length;
    if (n === total) {
      this.btn.textContent = this.cfg.allLabel || 'All';
      this.btn.classList.remove('msf-active');
    } else {
      this.btn.textContent = n === 0 ? 'None selected' : n + ' of ' + total + ' selected';
      this.btn.classList.add('msf-active');
    }
  };

  /* null = no filtering (everything checked); otherwise Set of values */
  MSFilter.prototype.selected = function () {
    if (this.count() === this.options.length) return null;
    var s = new Set(), self = this;
    this.options.forEach(function (o) { if (self.checked[o.v]) s.add(o.v); });
    return s;
  };

  MSFilter.prototype.pass = function (value) {
    var s = this.selected();
    return s === null || s.has(value);
  };

  MSFilter.prototype.reset = function () {
    var self = this;
    this.options.forEach(function (o) { self.checked[o.v] = true; });
    this.mount.querySelectorAll('.msf-list input').forEach(function (i) { i.checked = true; });
    this.updateBtn();
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  global.MSFilter = MSFilter;
})(window);
