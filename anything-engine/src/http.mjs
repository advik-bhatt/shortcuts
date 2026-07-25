// Tiny HTTP helper: JSON fetch with a timeout and a real User-Agent.
// Every network source in this engine goes through here so that a blocked
// or slow endpoint degrades to a clean error instead of hanging the run.

const UA = 'anything-engine/0.1 (+https://github.com/advik-bhatt/shortcuts)';

export async function fetchJson(url, { timeoutMs = 12000, headers = {} } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: { 'User-Agent': UA, Accept: 'application/json', ...headers },
    });
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status} for ${url}`);
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Returns { ok, value } | { ok:false, reason } instead of throwing, so a
// single dead source never kills a multi-source resolve.
export async function tryJson(url, opts) {
  try {
    return { ok: true, value: await fetchJson(url, opts) };
  } catch (e) {
    return { ok: false, reason: e.message, status: e.status };
  }
}
