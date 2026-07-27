// ECERankings Frontend Application - Logic

const STATE = {
  areas: null,
  institutions: null,
  dataCache: new Map(),
  
  startYear: 2016,
  endYear: 2026,
  minYearAllowed: 2000,
  maxYearAllowed: 2026,
  
  region: 'all',
  selectedAreas: new Set(),
  elements: {}
};

const REGIONS = {
  'us': ['US'],
  'ca': ['CA'],
  'north-america': ['US', 'CA', 'MX'],
  'europe': ['GB', 'DE', 'FR', 'IT', 'ES', 'NL', 'CH', 'SE', 'BE', 'DK', 'FI', 'NO', 'AT', 'PL', 'GR', 'PT', 'IE'],
  'asia': ['CN', 'JP', 'KR', 'IN', 'TW', 'SG', 'HK', 'MY', 'TH', 'VN'],
  'oceania': ['AU', 'NZ']
};

function getCountryEmoji(countryCode) {
  if (!countryCode) return '';
  const codePoints = countryCode.toUpperCase().split('').map(char => 127397 + char.charCodeAt(0));
  return String.fromCodePoint(...codePoints);
}

async function init() {
  cacheElements();
  bindEvents();
  initDualSlider();
  showLoading(true);
  
  try {
    const [areasRes, instRes] = await Promise.all([
      fetch('data/areas.json').then(r => r.json()),
      fetch('data/institutions.json').then(r => r.json())
    ]);
    
    STATE.areas = areasRes.areas;
    STATE.institutions = instRes;
    
    // Select default areas
    Object.entries(STATE.areas).forEach(([key, area]) => {
      if (area.default_on) STATE.selectedAreas.add(key);
    });
    
    renderSidebarPills();
    await updateRankings();
  } catch (err) {
    console.error("Init Error:", err);
    STATE.elements.rankingBody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: red;">Failed to load data. Ensure you are running a local server.</td></tr>`;
  } finally {
    showLoading(false);
  }
}

function cacheElements() {
  STATE.elements = {
    yearMinInput: document.getElementById('year-min'),
    yearMaxInput: document.getElementById('year-max'),
    sliderTrack: document.getElementById('slider-track'),
    displayStart: document.getElementById('display-start'),
    displayEnd: document.getElementById('display-end'),
    
    regionFilter: document.getElementById('region-filter'),
    areasContainer: document.getElementById('areas-container'),
    toggleAllAreas: document.getElementById('toggle-all-areas'),
    
    rankingBody: document.getElementById('ranking-tbody'),
    resultsCount: document.getElementById('results-count'),
    loadingOverlay: document.getElementById('loading-overlay')
  };
}

// --- Dual Range Slider Logic ---
function initDualSlider() {
  const minSlider = STATE.elements.yearMinInput;
  const maxSlider = STATE.elements.yearMaxInput;
  
  function updateSliderVisuals() {
    let minVal = parseInt(minSlider.value);
    let maxVal = parseInt(maxSlider.value);
    
    if (minVal > maxVal) {
      // Swap visually if they cross
      let tmp = minVal;
      minVal = maxVal;
      maxVal = tmp;
    }
    
    STATE.elements.displayStart.textContent = minVal;
    STATE.elements.displayEnd.textContent = maxVal;
    STATE.startYear = minVal;
    STATE.endYear = maxVal;
    
    const range = STATE.maxYearAllowed - STATE.minYearAllowed;
    const minPercent = ((minVal - STATE.minYearAllowed) / range) * 100;
    const maxPercent = ((maxVal - STATE.minYearAllowed) / range) * 100;
    
    STATE.elements.sliderTrack.style.left = `${minPercent}%`;
    STATE.elements.sliderTrack.style.width = `${maxPercent - minPercent}%`;
  }

  const debouncedUpdateData = debounce(() => updateRankings(), 300);

  minSlider.addEventListener('input', () => {
    updateSliderVisuals();
    debouncedUpdateData();
  });
  
  maxSlider.addEventListener('input', () => {
    updateSliderVisuals();
    debouncedUpdateData();
  });
  
  updateSliderVisuals(); // Initialize track position
}
// -------------------------------

function bindEvents() {
  STATE.elements.regionFilter.addEventListener('change', (e) => {
    STATE.region = e.target.value;
    updateRankings();
  });

  STATE.elements.toggleAllAreas.addEventListener('click', () => {
    const allKeys = Object.keys(STATE.areas);
    const pillButtons = document.querySelectorAll('.pill-btn');
    
    if (STATE.selectedAreas.size === allKeys.length) {
      STATE.selectedAreas.clear();
      pillButtons.forEach(btn => btn.classList.remove('active'));
    } else {
      allKeys.forEach(k => STATE.selectedAreas.add(k));
      pillButtons.forEach(btn => btn.classList.add('active'));
    }
    updateRankings();
  });
}

function renderSidebarPills() {
  const container = STATE.elements.areasContainer;
  container.innerHTML = '';
  
  const clusters = {};
  Object.entries(STATE.areas).forEach(([key, area]) => {
    if (!clusters[area.cluster]) clusters[area.cluster] = [];
    clusters[area.cluster].push({ key, ...area });
  });
  
  Object.keys(clusters).sort().forEach(clusterName => {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'cluster-group';
    
    const title = document.createElement('div');
    title.className = 'cluster-title';
    title.textContent = clusterName;
    groupDiv.appendChild(title);
    
    const pillGroup = document.createElement('div');
    pillGroup.className = 'pill-group';
    
    clusters[clusterName].forEach(area => {
      const pill = document.createElement('button');
      pill.className = `pill-btn ${STATE.selectedAreas.has(area.key) ? 'active' : ''}`;
      pill.textContent = area.name;
      
      pill.addEventListener('click', () => {
        if (STATE.selectedAreas.has(area.key)) {
          STATE.selectedAreas.delete(area.key);
          pill.classList.remove('active');
        } else {
          STATE.selectedAreas.add(area.key);
          pill.classList.add('active');
        }
        updateRankings();
      });
      
      pillGroup.appendChild(pill);
    });
    
    groupDiv.appendChild(pillGroup);
    container.appendChild(groupDiv);
  });
}

async function fetchAreaData(areaKey) {
  if (STATE.dataCache.has(areaKey)) return STATE.dataCache.get(areaKey);
  try {
    const res = await fetch(`data/${areaKey}.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    STATE.dataCache.set(areaKey, data);
    return data;
  } catch (err) {
    return [];
  }
}

async function updateRankings() {
  showLoading(true);
  
  const fetchPromises = Array.from(STATE.selectedAreas).map(area => fetchAreaData(area));
  await Promise.all(fetchPromises);
  
  const instStats = new Map();
  
  for (const area of STATE.selectedAreas) {
    const areaData = STATE.dataCache.get(area) || [];
    const areaSums = new Map();
    for (const row of areaData) {
      if (row.y >= STATE.startYear && row.y <= STATE.endYear) {
        areaSums.set(row.i, (areaSums.get(row.i) || 0) + row.a);
      }
    }
    
    for (const [instId, sum] of areaSums.entries()) {
      if (!instStats.has(instId)) instStats.set(instId, { id: instId, areaCounts: new Map() });
      instStats.get(instId).areaCounts.set(area, sum);
    }
  }
  
  const numSelectedAreas = STATE.selectedAreas.size;
  let results = [];
  
  if (numSelectedAreas > 0) {
    for (const stats of instStats.values()) {
      let product = 1;
      for (const area of STATE.selectedAreas) {
        product *= ((stats.areaCounts.get(area) || 0) + 1);
      }
      stats.score = Math.pow(product, 1 / numSelectedAreas);
      if (stats.score > 1.0001) results.push(stats);
    }
  }
  
  if (STATE.region !== 'all') {
    const allowedCountries = REGIONS[STATE.region] || [];
    results = results.filter(stats => {
      const meta = STATE.institutions[stats.id];
      return meta && allowedCountries.includes(meta.country);
    });
  }
  
  results.sort((a, b) => b.score - a.score);
  
  renderTable(results);
  STATE.elements.resultsCount.textContent = `${results.length} institutions found`;
  showLoading(false);
}

function renderTable(results) {
  const tbody = STATE.elements.rankingBody;
  tbody.innerHTML = '';
  
  if (results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; padding: 2rem;">No data matches your criteria.</td></tr>`;
    return;
  }
  
  const displayResults = results.slice(0, 150);
  const fragment = document.createDocumentFragment();
  let currentRank = 1;
  let previousScore = -1;
  
  displayResults.forEach((stats, index) => {
    if (Math.abs(stats.score - previousScore) > 0.0001) currentRank = index + 1;
    previousScore = stats.score;
    
    const meta = STATE.institutions[stats.id] || { name: 'Unknown Institution', country: '' };
    const scoreVal = (stats.score - 1).toFixed(1);
    
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="col-rank">${currentRank}</td>
      <td class="col-inst">
        <span class="flag">${getCountryEmoji(meta.country)}</span>
        ${meta.name}
      </td>
      <td class="col-score">${scoreVal}</td>
    `;
    
    fragment.appendChild(tr);
  });
  
  tbody.appendChild(fragment);
}

function showLoading(show) {
  if (show) STATE.elements.loadingOverlay?.classList.add('active');
  else STATE.elements.loadingOverlay?.classList.remove('active');
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

document.addEventListener('DOMContentLoaded', init);
