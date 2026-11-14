// BiologyRankings — entry point.
// Boots the shared rankings engine with Biology-specific parameters.

export * from '../core/engine.js';
import { initRankingsApp } from '../core/engine.js';

initRankingsApp({
  fieldId: 'biology',
  name: 'BiologyRankings',
  exportPrefix: 'biorankings',
  methodologyHref: '../methodology.html',
  hasHospitalRollup: true,
  hasSectorFilter: false,
  hasPrerenderedTable: false,
});
