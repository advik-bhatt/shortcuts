// engine.mjs — the orchestrator that turns a GOAL into a BUILD PLAN.
//
// Pipeline (all deterministic, no LLM in the loop):
//   goal --decompose--> capabilities
//   each capability --resolve--> ranked real components (picks)
//   each top software pick --expand--> its real dependency graph
//   assemble --> { stages, software[], bom[](parts w/ price+qty), missing[] }
//
// The output is directly what the founder asked for: the components that exist,
// the parts to order, and (via the dossier renderer) exactly what to build.
import { decompose } from './decompose.mjs';
import { resolve } from './resolve.mjs';
import { expand } from './expand.mjs';

export async function plan(goal, { perCapability = 4, expandTop = true, expandDepth = 1 } = {}) {
  const decomposition = decompose(goal);
  const stages = [];
  const software = [];
  const bom = [];
  const optional = [];
  const missing = [];

  for (const cap of decomposition.capabilities) {
    // A parts-only stage needs EVERY required part in the BOM, not a top-N
    // shortlist (you don't pick one motor OR one belt — you order all of them).
    // Software stages stay shortlisted: you choose one tool for the job.
    const partsOnly = Array.isArray(cap.kinds) && cap.kinds.length === 1 && cap.kinds[0] === 'part';
    const resolved = await resolve(cap, { limit: partsOnly ? 100 : perCapability });
    let graph = null;

    // Expand the dependency tree of the single best SOFTWARE pick, to make the
    // "built from things that already exist" claim concrete for this stage.
    const topSoftware = resolved.picks.find(
      (p) => p.kind === 'software' && ['npm', 'pypi', 'crates'].includes(p.registry)
    );
    if (expandTop && topSoftware) {
      try {
        graph = await expand(topSoftware, { depth: expandDepth });
      } catch {
        graph = null;
      }
    }

    if (!resolved.picks.length) {
      missing.push({ capability: cap.capability || cap.query, notes: resolved.notes });
    }

    for (const p of resolved.picks) {
      if (p.kind === 'part') {
        // qty 0 in the index marks an OPTIONAL part (e.g. the laser upgrade) —
        // list it separately and keep it out of the required total.
        const row = {
          capability: resolved.capability,
          name: p.name,
          what: p.what,
          qty: p.qty || 1,
          unit_usd: p.price_usd || 0,
          line_usd: (p.qty || 1) * (p.price_usd || 0),
          source_url: p.source_url,
          verified: !!p.verified,
        };
        if (p.qty === 0) optional.push({ ...row, qty: 1, line_usd: p.price_usd || 0, optional: true });
        else bom.push(row);
      } else {
        software.push({
          capability: resolved.capability,
          name: p.name,
          what: p.what,
          registry: p.registry,
          license: p.license,
          source_url: p.source_url,
          popularity: p.popularity || 0,
          verified: !!p.verified,
        });
      }
    }

    stages.push({
      capability: resolved.capability,
      query: resolved.query,
      registries: resolved.registries,
      picks: resolved.picks,
      dep_graph: graph,
      notes: resolved.notes,
    });
  }

  // De-duplicate the flat software/bom lists (a component can satisfy >1 stage).
  const uniqBy = (arr, keyFn) => {
    const seen = new Set();
    return arr.filter((x) => {
      const k = keyFn(x);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  };
  const softwareU = uniqBy(software, (s) => `${s.registry}:${s.name}`);
  const bomU = uniqBy(bom, (b) => b.name);
  const optionalU = uniqBy(optional, (b) => b.name);
  const bom_total_usd = bomU.reduce((n, b) => n + (b.line_usd || 0), 0);

  return {
    goal,
    generated_from: 'anything-engine',
    decomposition: {
      matched: decomposition.matched,
      recipe: decomposition.recipe,
      recipe_file: decomposition.recipe_file || null,
      domain: decomposition.domain,
      note: decomposition.note || null,
    },
    stages,
    software: softwareU,
    bom: bomU,
    optional: optionalU,
    bom_total_usd: Math.round(bom_total_usd * 100) / 100,
    missing,
  };
}
