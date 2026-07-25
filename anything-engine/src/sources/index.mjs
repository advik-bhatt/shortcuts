// Curated index source — the verified component catalog that covers what live
// egress can't: physical parts (with real prices/quantities) and repos that
// live behind a blocked search API. Every entry is human/agent-verified and
// carries its real source URL. Files live in ../../index/*.json.
//
// This is the engine's answer to "fuck the limitation, find a better path":
// where the network won't let code reach a source live, the same real data is
// captured into a verified index and served identically.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX_DIR = join(HERE, '..', '..', 'index');

export const id = 'index';

let CACHE = null;

function load() {
  if (CACHE) return CACHE;
  const out = [];
  if (existsSync(INDEX_DIR)) {
    for (const f of readdirSync(INDEX_DIR)) {
      if (!f.endsWith('.json')) continue;
      try {
        const doc = JSON.parse(readFileSync(join(INDEX_DIR, f), 'utf8'));
        for (const c of doc.components || []) out.push({ _file: f, ...c });
      } catch (e) {
        // A malformed index file should not take down the whole engine.
        process.stderr.write(`[index] skipped ${f}: ${e.message}\n`);
      }
    }
  }
  CACHE = out;
  return out;
}

const tokens = (s) =>
  (s || '')
    .toLowerCase()
    .split(/[^a-z0-9+]+/)
    .filter((t) => t.length > 1);

const STOP = new Set(['the', 'and', 'for', 'with', 'runs', 'over', 'drives']);

// Does this entry belong to the stage we're resolving? Compares the entry's
// own capability tag against the stage capability by significant-token overlap.
function capAffinity(entryCap, stageCap) {
  if (!entryCap || !stageCap) return false;
  const a = new Set(tokens(entryCap).filter((t) => !STOP.has(t)));
  const b = tokens(stageCap).filter((t) => !STOP.has(t));
  return b.some((t) => a.has(t));
}

export async function search(query, { limit = 8, kinds = null, capability = null } = {}) {
  const all = load();
  const qt = tokens(query);
  if (!qt.length) return { ok: true, components: [] };

  // When the caller names a capability and this index has entries tagged for
  // it, scope strictly to those — that is what keeps a "design to toolpath"
  // entry out of the "firmware" stage even though both mention g-code.
  const anyAffinity = capability && all.some((c) => capAffinity(c.capability, capability));

  const scored = [];
  for (const c of all) {
    if (kinds && !kinds.includes(c.kind)) continue;
    const affine = capability ? capAffinity(c.capability, capability) : false;
    if (anyAffinity && !affine) continue; // stage is scoped; drop off-capability entries
    const hay = new Set(tokens([c.name, c.what, c.capability, (c.keywords || []).join(' ')].join(' ')));
    let hit = 0;
    for (const t of qt) if (hay.has(t)) hit += 1;
    const kw = hit / qt.length;
    if (!affine && !hit) continue;
    // Capability-tagged entries lead; keyword overlap orders within the stage.
    scored.push({ score: (affine ? 1 : 0) + kw, component: c });
  }
  scored.sort((a, b) => b.score - a.score);
  const components = scored.slice(0, limit).map(({ component }) => ({
    name: component.name,
    kind: component.kind,
    what: component.what || '',
    source_url: component.source_url || '',
    registry: component.registry || 'index',
    license: component.license || '',
    popularity: component.popularity || 0,
    price_usd: component.price_usd || 0,
    qty: component.qty || 0,
    verified: component.verified !== false,
    version: '',
  }));
  return { ok: true, components };
}
