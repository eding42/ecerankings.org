// Year strip: one column per year with a bar of that year's output, and a
// band over the chosen years. Drag across columns to choose; the arrow keys
// move the band and, in range mode, Shift+arrow resizes it.
//
// mode 'range'  -> a from–to span; onChange(fromYear, toYear).
// mode 'single' -> one year or none; onChange(year | null). Pressing the
//                  chosen year again clears it.

const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

/**
 * @param {HTMLElement} root
 * @param {{mode?: 'range'|'single', label: string, onChange: Function, onPreview?: Function}} options
 */
export function createYearStrip(root, { mode = 'range', label, onChange, onPreview }) {
  const single = mode === 'single';
  root.classList.add('ys');
  root.innerHTML =
    `<div class="ys-plot" tabindex="0" role="group"><div class="ys-band" hidden></div><div class="ys-tip" hidden></div></div>` +
    `<div class="ys-axis" aria-hidden="true"></div>`;
  const plot = root.querySelector('.ys-plot');
  const band = root.querySelector('.ys-band');
  const tip = root.querySelector('.ys-tip');
  const axis = root.querySelector('.ys-axis');

  let years = [];      // [{year, values: number[], partial?: boolean, text?: string}]
  let a = null;        // chosen span as column indexes, or null when nothing is chosen
  let b = null;
  let drag = null;     // {anchor, moved, startedOn}
  let domainKey = '';

  const count = () => years.length;
  const colAt = (x) => {
    const r = plot.getBoundingClientRect();
    return Math.max(0, Math.min(count() - 1, Math.floor(((x - r.left) / r.width) * count())));
  };
  const indexOf = (year) => years.findIndex((y) => y.year === year);

  function paint(lo, hi) {
    const n = count();
    const none = lo === null || !n;
    plot.querySelectorAll('.ys-col').forEach((col) => {
      const i = Number(col.dataset.i);
      col.classList.toggle('out', !none && (i < lo || i > hi));
    });
    axis.querySelectorAll('span').forEach((s) => {
      const i = Number(s.dataset.i);
      s.classList.toggle('on', !none && i >= lo && i <= hi);
    });
    band.hidden = none;
    if (!none) {
      band.style.left = `${(100 * lo) / n}%`;
      band.style.width = `${(100 * (hi - lo + 1)) / n}%`;
    }
    const text = none ? 'All years' : lo === hi ? String(years[lo].year) : `${years[lo].year} to ${years[hi].year}`;
    plot.setAttribute('aria-label', `${label}: ${text}. ${single
      ? 'Arrow keys change the year; Escape shows all years.'
      : 'Drag to choose years; arrow keys move the range, Shift and arrow keys resize it.'}`);
  }

  function labelAxis() {
    const n = count();
    if (!n) { axis.innerHTML = ''; return; }
    const room = Math.max(1, Math.floor((plot.clientWidth || 600) / 46));
    const every = Math.max(1, Math.ceil(n / room));
    let html = '';
    // Anchor on the newest year so it always carries a label.
    for (let i = n - 1; i >= 0; i -= every) {
      html = `<span data-i="${i}" style="left:${((100 * (i + 0.5)) / n).toFixed(2)}%">${years[i].year}</span>` + html;
    }
    axis.innerHTML = html;
  }

  function build() {
    plot.querySelectorAll('.ys-col').forEach((e) => e.remove());
    const series = years[0] ? years[0].values.length : 0;
    const bars = Array.from({ length: series }, (_, k) => `<i style="--series:var(--series-${k + 1})"></i>`).join('');
    years.forEach((y, i) => {
      const col = document.createElement('div');
      col.className = `ys-col${y.partial ? ' partial' : ''}`;
      col.dataset.i = i;
      col.style.setProperty('--i', i);
      col.innerHTML = `<span class="ys-bars${series > 1 ? ' multi' : ''}">${bars}</span>`;
      plot.append(col);
    });
    labelAxis();
  }

  function showTip(i) {
    const y = years[i];
    if (!y) return;
    tip.textContent = y.text || `${y.year} · ${fmt.format(y.values.reduce((s, v) => s + v, 0))}`;
    tip.hidden = false;
    tip.style.left = `clamp(70px, ${((100 * (i + 0.5)) / count()).toFixed(2)}%, calc(100% - 70px))`;
  }

  function commit(lo, hi) {
    if (single) onChange(lo === null ? null : years[lo].year);
    else onChange(years[lo].year, years[hi].year);
  }

  plot.addEventListener('pointerdown', (e) => {
    if (!count() || (e.pointerType === 'mouse' && e.button !== 0)) return;
    plot.setPointerCapture?.(e.pointerId);
    const i = colAt(e.clientX);
    // Shift-click stretches the current range to the pressed year.
    const anchor = !single && e.shiftKey && a !== null ? (Math.abs(i - a) > Math.abs(i - b) ? a : b) : i;
    drag = { anchor, moved: anchor !== i, startedOn: a !== null && a === b && a === i };
    root.classList.add('dragging');
    const lo = single ? i : Math.min(anchor, i), hi = single ? i : Math.max(anchor, i);
    paint(lo, hi);
    onPreview?.(years[lo].year, years[hi].year);
  });
  plot.addEventListener('pointermove', (e) => {
    if (!count()) return;
    const i = colAt(e.clientX);
    showTip(i);
    if (!drag) return;
    if (i !== drag.anchor) drag.moved = true;
    const lo = single ? i : Math.min(drag.anchor, i), hi = single ? i : Math.max(drag.anchor, i);
    paint(lo, hi);
    onPreview?.(years[lo].year, years[hi].year);
  });
  const release = (e) => {
    if (!drag) return;
    const i = colAt(e.clientX);
    const { anchor, moved, startedOn } = drag;
    drag = null;
    root.classList.remove('dragging');
    if (single && !moved && startedOn) { a = b = null; paint(null, null); commit(null, null); return; }
    a = single ? i : Math.min(anchor, i);
    b = single ? i : Math.max(anchor, i);
    paint(a, b);
    commit(a, b);
  };
  plot.addEventListener('pointerup', release);
  plot.addEventListener('pointercancel', () => {
    if (!drag) return;
    drag = null;
    root.classList.remove('dragging');
    paint(a, b);
    // Put back whatever the preview changed.
    if (a !== null) onPreview?.(years[a].year, years[b].year);
    else if (single) onPreview?.(null, null);
  });
  plot.addEventListener('pointerleave', () => { if (!drag) tip.hidden = true; });
  plot.addEventListener('blur', () => { tip.hidden = true; });

  plot.addEventListener('keydown', (e) => {
    const n = count();
    if (!n) return;
    if (e.key === 'Escape' && single && a !== null) {
      e.preventDefault();
      a = b = null; paint(null, null); commit(null, null);
      return;
    }
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const d = e.key === 'ArrowLeft' ? -1 : 1;
    let lo = a, hi = b;
    if (lo === null) { lo = hi = d > 0 ? 0 : n - 1; }
    else if (single) { lo = hi = Math.max(0, Math.min(n - 1, lo + d)); }
    else if (e.shiftKey) { hi = Math.max(lo, Math.min(n - 1, hi + d)); }
    else if (lo + d >= 0 && hi + d < n) { lo += d; hi += d; }
    if (lo === a && hi === b) return;
    a = lo; b = hi;
    paint(a, b);
    showTip(d > 0 ? b : a);
    commit(a, b);
  });

  if (typeof ResizeObserver !== 'undefined') {
    let width = 0;
    new ResizeObserver(() => {
      const w = Math.round(plot.clientWidth);
      if (w && w !== width) { width = w; labelAxis(); paint(a, b); }
    }).observe(plot);
  }

  return {
    /** Replace the bars. Columns are rebuilt only when the years or series change. */
    setData(next) {
      const key = `${next.map((y) => y.year).join(',')}|${next[0] ? next[0].values.length : 0}`;
      years = next;
      if (key !== domainKey) { domainKey = key; build(); }
      const max = Math.max(1e-9, ...years.flatMap((y) => y.values));
      plot.querySelectorAll('.ys-col').forEach((col) => {
        const y = years[Number(col.dataset.i)];
        col.classList.toggle('partial', Boolean(y.partial));
        col.querySelectorAll('i').forEach((bar, k) => {
          const v = y.values[k] || 0;
          bar.style.height = v > 0 ? `max(2px, ${((100 * v) / max).toFixed(2)}%)` : '0';
        });
      });
      paint(a, b);
    },
    /** Move the band. Years are inclusive; pass null for no selection. */
    setRange(fromYear, toYear = fromYear) {
      if (drag) return;
      if (fromYear === null || fromYear === undefined) { a = b = null; }
      else {
        const lo = indexOf(fromYear), hi = indexOf(toYear);
        a = lo < 0 ? 0 : lo;
        b = hi < 0 ? Math.max(a, count() - 1) : Math.max(a, hi);
      }
      paint(a, b);
    },
  };
}

// Years worth drawing: from the first year carrying at least `floor` of the
// peak (or `keep`, if earlier) to the last year with data. Sparse early years
// stay reachable from the year menus without flattening the strip.
export function denseStart(totals, keep, floor = 0.05) {
  const years = [...totals.keys()].sort((x, y) => x - y);
  if (!years.length) return keep;
  const peak = Math.max(...totals.values());
  const first = years.find((y) => totals.get(y) >= peak * floor) ?? years[0];
  return Math.min(first, keep);
}
