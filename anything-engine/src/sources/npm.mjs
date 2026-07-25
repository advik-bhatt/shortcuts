// npm source — JavaScript/Node packages. Live-reachable, no key.
import { tryJson } from '../http.mjs';

const SEARCH = 'https://registry.npmjs.org/-/v1/search';
const PKG = 'https://registry.npmjs.org';

export const id = 'npm';

export async function search(query, { limit = 5 } = {}) {
  const url = `${SEARCH}?text=${encodeURIComponent(query)}&size=${limit}`;
  const r = await tryJson(url);
  if (!r.ok) return { ok: false, reason: r.reason, components: [] };
  const components = (r.value.objects || []).map((o) => {
    const p = o.package;
    return {
      name: p.name,
      kind: 'software',
      what: p.description || '',
      source_url: p.links?.repository || p.links?.npm || `https://www.npmjs.com/package/${p.name}`,
      registry: 'npm',
      license: p.license || '',
      // npm exposes a 0..1 search score, not a download count. Scale to 0..1000
      // as an honest popularity proxy (relevance leads the ranking anyway).
      popularity: Math.round((o.score?.detail?.popularity || 0) * 1000),
      version: p.version || '',
    };
  });
  return { ok: true, components };
}

export async function deps(name) {
  const r = await tryJson(`${PKG}/${encodeURIComponent(name).replace('%40', '@')}`);
  if (!r.ok) return { ok: false, reason: r.reason, deps: [] };
  const latestTag = r.value['dist-tags']?.latest;
  const ver = r.value.versions?.[latestTag];
  const d = (ver && ver.dependencies) || {};
  const list = Object.entries(d).map(([n, req]) => ({ name: n, req, registry: 'npm' }));
  return { ok: true, deps: list, version: latestTag };
}
