// crates.io source — Rust packages. Live-reachable with a User-Agent.
// This is one of the registries that proves the engine's core claim: given a
// capability query it returns REAL existing components, no LLM involved.
import { tryJson } from '../http.mjs';

const API = 'https://crates.io/api/v1';

export const id = 'crates';

export async function search(query, { limit = 5 } = {}) {
  const url = `${API}/crates?q=${encodeURIComponent(query)}&per_page=${limit}`;
  const r = await tryJson(url);
  if (!r.ok) return { ok: false, reason: r.reason, components: [] };
  const components = (r.value.crates || []).map((c) => ({
    name: c.id,
    kind: 'software',
    what: c.description || '',
    source_url: c.repository || `https://crates.io/crates/${c.id}`,
    registry: 'crates',
    license: c.license || '',
    popularity: c.downloads || 0,
    version: c.newest_version || c.max_version || '',
  }));
  return { ok: true, components };
}

// Real dependency edges for a crate version — the machine-readable proof that
// "everything new is made of things that already exist."
export async function deps(name, version) {
  const meta = await tryJson(`${API}/crates/${encodeURIComponent(name)}`);
  if (!meta.ok) return { ok: false, reason: meta.reason, deps: [] };
  const v = version || meta.value.crate?.newest_version || meta.value.crate?.max_version;
  if (!v) return { ok: false, reason: 'no version', deps: [] };
  const r = await tryJson(`${API}/crates/${encodeURIComponent(name)}/${v}/dependencies`);
  if (!r.ok) return { ok: false, reason: r.reason, deps: [] };
  const list = (r.value.dependencies || [])
    .filter((d) => d.kind === 'normal' && !d.optional)
    .map((d) => ({ name: d.crate_id, req: d.req, registry: 'crates' }));
  return { ok: true, deps: list, version: v };
}
