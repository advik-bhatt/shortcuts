// GitHub source — repositories. The richest index of "things that already
// exist," but its search API needs open egress to api.github.com and, for a
// decent rate limit, a token in GITHUB_API_TOKEN.
//
// In a locked-down sandbox (like the one this was first built in) api.github.com
// search is blocked, so this adapter reports itself UNAVAILABLE and the engine
// falls back to the curated index. It is real code, gated by reachability — not
// a stub. On any normal network it returns live results.
import { tryJson } from '../http.mjs';

const API = 'https://api.github.com/search/repositories';

export const id = 'github';

export async function search(query, { limit = 5 } = {}) {
  const headers = { Accept: 'application/vnd.github+json' };
  const token = process.env.GITHUB_API_TOKEN; // a PUBLIC-scope PAT, not a repo-bound session token
  if (token) headers.Authorization = `Bearer ${token}`;
  const url = `${API}?q=${encodeURIComponent(query)}&sort=stars&order=desc&per_page=${limit}`;
  const r = await tryJson(url, { headers });
  if (!r.ok) {
    return { ok: false, unavailable: true, reason: `github search unavailable (${r.reason})`, components: [] };
  }
  const components = (r.value.items || []).map((repo) => ({
    name: repo.full_name,
    kind: 'software',
    what: repo.description || '',
    source_url: repo.html_url,
    registry: 'github',
    license: repo.license?.spdx_id || '',
    popularity: repo.stargazers_count || 0,
    version: '',
  }));
  return { ok: true, components };
}
