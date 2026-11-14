// ECERankings — entry point.
// Boots the shared rankings engine with ECE-specific parameters.

export * from './core/engine.js';
import { initRankingsApp } from './core/engine.js';

initRankingsApp({
  fieldId: 'ece',
  name: 'ECERankings',
  exportPrefix: 'ecerankings',
  methodologyHref: 'methodology.html',
  hasHospitalRollup: false,
  hasSectorFilter: true,
  hasPrerenderedTable: true,
});
