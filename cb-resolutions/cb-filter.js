/*
  Shared Community Board filter — single source of truth for which CBs
  the user has selected. Pages render a chip group via initCbFilter() and
  subscribe to selection changes via onCbFilterChange(callback).

  Selection persistence:
    1. URL query string ?cb=MCB2,MCB3  (authoritative — shareable links)
    2. localStorage 'cb-resolutions:selected' (backup for when ?cb absent)

  If neither is set, defaults to all known boards.
*/
(function () {
  const KNOWN = [
    { id: 'MCB2',  label: 'MCB2',  color: '#f59e0b' },
    { id: 'MCB3',  label: 'MCB3',  color: '#2563eb' },
    { id: 'MCB4',  label: 'MCB4',  color: '#16a34a' },
    { id: 'MCB5',  label: 'MCB5',  color: '#dc2626' },
    { id: 'MCB7',  label: 'MCB7',  color: '#9333ea' },
    { id: 'MCB8',  label: 'MCB8',  color: '#0891b2' },
    { id: 'MCB10', label: 'MCB10', color: '#65a30d' },
  ];
  const STORAGE_KEY = 'cb-resolutions:selected';

  let selected = readSelected();
  const subscribers = [];

  function readSelected() {
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get('cb');
    if (fromUrl !== null) {
      const ids = fromUrl.split(',').map(s => s.trim()).filter(Boolean);
      if (ids.length) return ids.filter(id => KNOWN.some(k => k.id === id));
    }
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const ids = JSON.parse(stored);
        if (Array.isArray(ids) && ids.length) {
          return ids.filter(id => KNOWN.some(k => k.id === id));
        }
      }
    } catch (e) { /* localStorage unavailable */ }
    return KNOWN.map(k => k.id);
  }

  function writeSelected() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch (e) { /* ignore */ }
    const url = new URL(location.href);
    if (selected.length === KNOWN.length) {
      url.searchParams.delete('cb');
    } else {
      url.searchParams.set('cb', selected.join(','));
    }
    history.replaceState(null, '', url.toString());
    rewriteNavLinks();
  }

  function rewriteNavLinks() {
    // Carry the ?cb= param across pill-nav links so the user's selection
    // persists when they switch between Overview / chart subpages. Card
    // links on the hub page get the same treatment.
    document.querySelectorAll('a[data-cb-link]').forEach(a => {
      const target = new URL(a.dataset.cbLink, location.href);
      if (selected.length === KNOWN.length) {
        target.searchParams.delete('cb');
      } else {
        target.searchParams.set('cb', selected.join(','));
      }
      a.href = target.toString();
    });
  }

  function notify() {
    for (const cb of subscribers) {
      try { cb(selected.slice()); } catch (e) { console.error(e); }
    }
  }

  function setSelected(ids) {
    // Always keep at least one CB selected. If the user deselects the
    // last one, snap back to "all" rather than render empty charts.
    const filtered = ids.filter(id => KNOWN.some(k => k.id === id));
    selected = filtered.length ? filtered : KNOWN.map(k => k.id);
    writeSelected();
    renderChips();
    notify();
  }

  function renderChips() {
    const root = document.getElementById('cb-filter');
    if (!root) return;
    const all = selected.length === KNOWN.length;
    const none = selected.length === 0;

    root.innerHTML = '';

    const label = document.createElement('span');
    label.className = 'cb-filter-label';
    label.textContent = 'Show:';
    root.appendChild(label);

    const allChip = chip('All', all, () => setSelected(KNOWN.map(k => k.id)));
    root.appendChild(allChip);

    const noneChip = chip('None', none, () => setSelected([]));
    root.appendChild(noneChip);

    KNOWN.forEach(k => {
      const active = selected.includes(k.id);
      const c = chip(k.label, active, () => {
        const next = active
          ? selected.filter(id => id !== k.id)
          : [...selected, k.id];
        setSelected(next);
      }, k.color);
      root.appendChild(c);
    });
  }

  function chip(text, active, onClick, color) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'cb-chip' + (active ? ' active' : '');
    if (color && active) {
      b.style.backgroundColor = color;
      b.style.borderColor = color;
    }
    if (color) {
      const dot = document.createElement('span');
      dot.className = 'cb-chip-dot';
      dot.style.backgroundColor = color;
      b.appendChild(dot);
    }
    b.appendChild(document.createTextNode(text));
    b.addEventListener('click', onClick);
    return b;
  }

  // Public API
  window.CbFilter = {
    KNOWN,
    get selected() { return selected.slice(); },
    colorFor(id) {
      const k = KNOWN.find(k => k.id === id);
      return k ? k.color : '#6b7280';
    },
    onChange(cb) { subscribers.push(cb); },
    init() {
      renderChips();
      rewriteNavLinks();
    },
  };
})();
