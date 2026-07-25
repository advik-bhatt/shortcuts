// PyPI source — Python packages. Live-reachable, no key.
// PyPI retired its JSON/XML-RPC *search* endpoint, so this adapter is a
// name-resolver, not a fuzzy search: recipes hand it exact package names
// (the queries carry them), and it confirms existence + returns real metadata
// and real dependency edges. Honest about the limitation instead of faking it.
import { tryJson } from '../http.mjs';

const API = 'https://pypi.org/pypi';

export const id = 'pypi';

function candidates(query) {
  const q = query.trim();
  const out = new Set([q, q.toLowerCase()]);
  if (/\s/.test(q)) {
    const words = q.toLowerCase().split(/\s+/);
    // Recipe queries lead with the likely package name ("cadquery parametric
    // cad ..."), so try the first words first, then joined forms, then the last.
    out.add(words[0]);
    if (words.length > 1) out.add(`${words[0]}-${words[1]}`);
    out.add(words.join('-'));
    out.add(words.join(''));
    out.add(words[words.length - 1]);
  }
  return [...out];
}

async function resolve(name) {
  const r = await tryJson(`${API}/${encodeURIComponent(name)}/json`);
  if (!r.ok) return null;
  const info = r.value.info || {};
  return {
    name: info.name || name,
    kind: 'software',
    what: info.summary || '',
    source_url:
      info.project_urls?.Source ||
      info.project_urls?.Homepage ||
      info.home_page ||
      `https://pypi.org/project/${info.name || name}/`,
    registry: 'pypi',
    license: info.license || '',
    popularity: 0, // PyPI JSON does not expose download counts; ranked below registries that do.
    version: info.version || '',
    _requires: info.requires_dist || [],
  };
}

export async function search(query, { limit = 5 } = {}) {
  const found = [];
  for (const c of candidates(query)) {
    if (found.length >= limit) break;
    const hit = await resolve(c);
    if (hit && !found.some((f) => f.name.toLowerCase() === hit.name.toLowerCase())) found.push(hit);
  }
  if (!found.length) {
    return { ok: false, reason: `no PyPI package resolves for "${query}" (PyPI has no fuzzy search API)`, components: [] };
  }
  return { ok: true, components: found.map(({ _requires, ...c }) => c) };
}

export async function deps(name) {
  const hit = await resolve(name);
  if (!hit) return { ok: false, reason: 'not found', deps: [] };
  // requires_dist entries look like "numpy (>=1.20) ; extra == 'dev'" — keep
  // only the hard runtime deps (drop anything gated by an extra marker).
  const list = (hit._requires || [])
    .filter((s) => !/extra\s*==/.test(s))
    .map((s) => {
      const m = s.match(/^([A-Za-z0-9._-]+)\s*(.*)$/);
      return m ? { name: m[1], req: (m[2] || '').split(';')[0].trim(), registry: 'pypi' } : null;
    })
    .filter(Boolean);
  return { ok: true, deps: list, version: hit.version };
}
