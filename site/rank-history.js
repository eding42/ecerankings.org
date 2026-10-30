// Use the same ordered results and tie policy as the table. Annual ranks must
// include every eligible institution, even those outside the visible rows.
export function rankResults(results, {
  idForResult = result => result.id,
  scoreForResult = result => result.score,
  rankForResult,
  tieTolerance = 0.0001
} = {}) {
  const ranks = new Map();
  let rank = 1;
  let previousScore;
  results.forEach((result, index) => {
    if (rankForResult) {
      ranks.set(idForResult(result), rankForResult(result));
      return;
    }
    const score = scoreForResult(result);
    if (index === 0 || tieTolerance === null || Math.abs(score - previousScore) > tieTolerance) {
      rank = index + 1;
    }
    ranks.set(idForResult(result), rank);
    previousScore = score;
  });
  return ranks;
}

export function computeAnnualRanks({ startYear, endYear, rankingsForYear, ...rankOptions }) {
  const years = [];
  for (let year = startYear; year <= endYear; year++) {
    years.push({ year, ranks: rankResults(rankingsForYear(year), rankOptions) });
  }
  return years;
}

export function institutionHistory(annualRanks, institutionId) {
  return annualRanks.map(({ year, ranks }) => ({ year, rank: ranks.get(institutionId) ?? null }));
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}

export function renderRankHistory(history, institutionName, scope = 'selected areas and region') {
  if (!history.length) return '';
  const ranked = history.filter(point => point.rank !== null);
  const yearRange = history.length === 1 ? history[0].year : `${history[0].year}–${history.at(-1).year}`;
  let html = `<section class="rank-trend" aria-label="Annual ranking history">
    <span class="rank-trend-caption">Annual rank</span>
    <p class="rank-trend-sr-only">Each year ranked separately using the ${escapeHTML(scope)}. Higher is better; gaps mean no ranked output.</p>`;

  if (ranked.length) {
    const width = 260, height = 60;
    const left = 14, right = 30, top = 14, bottom = 16;
    const worst = Math.max(...ranked.map(point => point.rank), 2);
    const step = Math.max(1, 10 ** Math.floor(Math.log10(worst / 3)));
    const maxRank = Math.ceil(worst / step) * step;
    const x = index => history.length === 1 ? (left + width - right) / 2
      : left + index * (width - left - right) / (history.length - 1);
    const y = rank => top + (rank - 1) * (height - top - bottom) / (maxRank - 1);
    const format = number => number.toFixed(2);
    html += `<svg class="rank-trend-chart" viewBox="0 0 ${width} ${height}" role="group" aria-label="${escapeHTML(institutionName)} annual ranking, ${yearRange}">
      <title>${escapeHTML(institutionName)}: annual rank, ${yearRange}</title>`;
    // Only the first and last years are labelled to keep this a small sparkline.
    const endpoints = history.length === 1 ? [0] : [0, history.length - 1];
    for (const index of endpoints) {
      html += `<text class="rank-trend-label" x="${format(x(index))}" y="${height - 1}" text-anchor="middle">${history[index].year}</text>`;
    }
    let path = '', connected = false;
    history.forEach((point, index) => {
      if (point.rank === null) { connected = false; return; }
      path += `${connected ? 'L' : 'M'}${format(x(index))},${format(y(point.rank))} `;
      connected = true;
    });
    html += `<path class="rank-trend-line" d="${path.trim()}"/>`;
    history.forEach((point, index) => {
      if (point.rank === null) return;
      const px = x(index), py = y(point.rank);
      const tooltipX = Math.max(0, Math.min(px - 40, width - 80));
      const tooltipY = py < top + 12 ? py + 7 : py - 24;
      html += `<g class="rank-trend-point" tabindex="0" role="img" aria-label="${point.year}: rank ${point.rank}">
        <title>${point.year}: #${point.rank}</title>
        <circle class="rank-trend-hit" cx="${format(px)}" cy="${format(py)}" r="7"/>
        <circle class="rank-trend-dot" cx="${format(px)}" cy="${format(py)}" r="2"/>
        <g class="rank-trend-tooltip" aria-hidden="true">
          <rect x="${format(tooltipX)}" y="${format(tooltipY)}" width="80" height="20" rx="4"/>
          <text x="${format(tooltipX + 40)}" y="${format(tooltipY + 14)}" text-anchor="middle">${point.year}: #${point.rank}</text>
        </g>
      </g>`;
    });
    // The latest rank is the only persistent value label; other values appear on hover/focus.
    const last = history.at(-1);
    if (last.rank !== null) {
      html += `<text class="rank-trend-value" x="${format(x(history.length - 1) + 7)}" y="${format(y(last.rank) + 3)}">#${last.rank}</text>`;
    }
    html += '</svg>';
  } else {
    html += '<p class="rank-trend-empty">No ranked output in these years.</p>';
  }
  html += '<dl class="rank-trend-data rank-trend-sr-only" aria-label="Year-by-year ranks">';
  for (const point of history) {
    html += `<div><dt>${point.year}</dt><dd>${point.rank === null ? 'Not ranked' : `#${point.rank}`}</dd></div>`;
  }
  return html + '</dl></section>';
}
