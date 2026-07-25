// resolve() — the heart of the "search engine" half.
// Given ONE capability (a thing the build needs) it fans out across the named
// component sources, merges, de-dupes, and ranks by real popularity/verified
// signal. No LLM: the ranking is download counts, stars, and verified-index
// membership. This is the Google-for-buildable-components primitive.
import { getSource, ALL_SOFTWARE_SOURCES } from './registry.mjs';

function dedupe(components) {
  const seen = new Map();
  for (const c of components) {
    const key = `${c.registry}:${c.name}`.toLowerCase();
    const prev = seen.get(key);
    if (!prev || (c.popularity || 0) > (prev.popularity || 0)) seen.set(key, c);
  }
  return [...seen.values()];
}

const tok = (s) =>
  (s || '')
    .toLowerCase()
    .split(/[^a-z0-9+]+/)
    .filter((t) => t.length > 1);

// How well a component answers THIS query — token overlap of the query against
// the component name + description. Cross-registry popularity numbers (crates
// downloads vs github stars vs npm score) are not comparable, so relevance
// leads and popularity only breaks ties within a relevance bucket.
function relevance(queryTokens, c) {
  if (!queryTokens.length) return 0;
  const hay = new Set(tok(`${c.name} ${c.what}`));
  let hit = 0;
  for (const t of queryTokens) if (hay.has(t)) hit += 1;
  return hit / queryTokens.length;
}

// Rank: relevance bucket first, then a verified item wins the tie (confirmed,
// possibly orderable), then raw popularity within the bucket.
function makeRank(query) {
  const qt = tok(query);
  return (a, b) => {
    const ra = Math.round(relevance(qt, a) * 4);
    const rb = Math.round(relevance(qt, b) * 4);
    if (rb !== ra) return rb - ra;
    if (!!b.verified !== !!a.verified) return b.verified ? 1 : -1;
    return (b.popularity || 0) - (a.popularity || 0);
  };
}

export async function resolve(capability, { limit = 5 } = {}) {
  const query = capability.query || capability.capability || '';
  // A capability may constrain the kind of component it wants (e.g. a parts
  // stage wants kind "part", not a firmware repo that merely shares keywords).
  const kinds = Array.isArray(capability.kinds) && capability.kinds.length ? capability.kinds : null;
  const wantsSoftware = !kinds || kinds.some((k) => k !== 'part');

  const registries = (capability.registries || ALL_SOFTWARE_SOURCES.join(','))
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  // Always consult the curated index too — it is where verified parts and
  // egress-blocked repos live. Skip the live software registries entirely for a
  // parts-only stage (nothing on npm/crates is a NEMA17 motor).
  let toQuery = [...new Set([...registries, 'index'])];
  if (!wantsSoftware) toQuery = toQuery.filter((r) => r === 'index');

  const notes = [];
  const results = await Promise.all(
    toQuery.map(async (rid) => {
      const src = getSource(rid);
      if (!src) {
        notes.push(`unknown source "${rid}"`);
        return [];
      }
      try {
        const r = await src.search(query, {
          limit,
          kinds,
          capability: capability.capability || null,
          domain: capability.domain || null,
        });
        if (!r.ok) {
          notes.push(`${rid}: ${r.reason}`);
          return [];
        }
        return r.components;
      } catch (e) {
        notes.push(`${rid}: ${e.message}`);
        return [];
      }
    })
  );

  // Enforce the kind constraint on the merged set (live sources ignore `kinds`).
  const filtered = kinds ? results.flat().filter((c) => kinds.includes(c.kind)) : results.flat();
  const merged = dedupe(filtered).sort(makeRank(query));
  return {
    capability: capability.capability || query,
    query,
    registries: toQuery,
    picks: merged.slice(0, limit),
    notes,
  };
}
