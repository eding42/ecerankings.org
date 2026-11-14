// EarthSpaceRankings — entry point.
// Boots the shared rankings engine with Earth & Space-specific parameters.

export * from '../core/engine.js';
import { initRankingsApp } from '../core/engine.js';

initRankingsApp({
  fieldId: 'earth-space',
  name: 'EarthSpaceRankings',
  exportPrefix: 'earthspacerankings',
  methodologyHref: 'methodology.html',
  hasHospitalRollup: false,
  hasSectorFilter: true,
  hasPrerenderedTable: false,
});
