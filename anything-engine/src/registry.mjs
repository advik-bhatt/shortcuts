// The set of component sources the engine can query, keyed by id.
// Adding a new index of "things that exist" (Octopart, Thingiverse, a parts
// distributor API) is a one-file drop-in here.
import * as crates from './sources/crates.mjs';
import * as npm from './sources/npm.mjs';
import * as pypi from './sources/pypi.mjs';
import * as github from './sources/github.mjs';
import * as index from './sources/index.mjs';

export const SOURCES = { crates, npm, pypi, github, index };

export const ALL_SOFTWARE_SOURCES = ['crates', 'npm', 'pypi', 'github'];

export function getSource(name) {
  return SOURCES[name] || null;
}

// Dependency expansion is registry-specific; only some sources expose edges.
export async function depsFor(component) {
  const src = SOURCES[component.registry];
  if (!src || typeof src.deps !== 'function') return { ok: false, reason: 'no dep graph for ' + component.registry, deps: [] };
  return src.deps(component.name, component.version);
}
