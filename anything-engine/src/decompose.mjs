// decompose() — turns a GOAL ("a thing that doesn't exist yet") into an ordered
// list of CAPABILITIES (subsystems), each with a query that finds real parts.
//
// Composition strategy, in priority order:
//   1. A matching RECIPE from recipes/*.json (no LLM, fully deterministic).
//      Recipes are the reusable decompositions; the library grows over time.
//   2. If no recipe matches: a single-capability fallback that searches the raw
//      goal across every source. Shallow but still returns real components, and
//      flags that a recipe should be added.
//   3. An optional LLM planner hook (llmPlan) for novel goals. It is NOT wired
//      to any model here — calling it without configuration throws honestly,
//      because the retrieval/composition core is deliberately LLM-free.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const RECIPE_DIR = join(HERE, '..', 'recipes');

const tokens = (s) =>
  (s || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length > 2);

const STOP = new Set(['the', 'and', 'for', 'from', 'with', 'that', 'this', 'build', 'make', 'create', 'into', 'your', 'you']);

export function loadRecipes() {
  const out = [];
  if (!existsSync(RECIPE_DIR)) return out;
  for (const f of readdirSync(RECIPE_DIR)) {
    if (!f.endsWith('.json')) continue;
    try {
      out.push({ _file: f, ...JSON.parse(readFileSync(join(RECIPE_DIR, f), 'utf8')) });
    } catch (e) {
      process.stderr.write(`[recipes] skipped ${f}: ${e.message}\n`);
    }
  }
  return out;
}

function score(goalTokens, recipe) {
  const rt = new Set(
    [...tokens(recipe.goal), ...(recipe.aliases || []).flatMap(tokens)].filter((t) => !STOP.has(t))
  );
  let hit = 0;
  for (const t of goalTokens) if (!STOP.has(t) && rt.has(t)) hit += 1;
  return hit;
}

export function decompose(goal, { recipes = loadRecipes() } = {}) {
  const gt = tokens(goal);
  let best = null;
  let bestScore = 0;
  for (const r of recipes) {
    const s = score(gt, r);
    if (s > bestScore) {
      bestScore = s;
      best = r;
    }
  }

  if (best && bestScore > 0) {
    return {
      goal,
      matched: true,
      recipe: best.goal,
      recipe_file: best._file,
      domain: best.domain || '',
      match_score: bestScore,
      capabilities: best.capabilities,
    };
  }

  // Fallback: no recipe. Treat the goal as one capability so the engine still
  // returns real components, and flag that a recipe is missing.
  return {
    goal,
    matched: false,
    recipe: null,
    domain: '',
    match_score: 0,
    capabilities: [{ capability: goal, query: goal, registries: 'crates,npm,pypi,github' }],
    note: 'No recipe matched. Returning a flat search over all sources. Add a recipe in recipes/ to decompose this goal into subsystems.',
  };
}

// Optional planner for goals with no recipe. Intentionally unconfigured: the
// engine's core is LLM-free by design. Wire a model here only if you want
// machine-proposed decompositions (which must still be verified against real
// registries before they are trusted).
export async function llmPlan() {
  throw new Error('llmPlan is not configured: the composition core is LLM-free. Add a recipe instead, or wire a planner explicitly.');
}
