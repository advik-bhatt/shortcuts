# anything-engine

**A search engine for agents that finds the real, existing components you can compose to build a thing that doesn't exist yet — then emits an orderable build dossier.**

You give it a goal ("graphic design to hardware"). It decomposes the goal into
subsystems, searches real component indexes for each subsystem, walks the real
dependency graph of what it finds (because everything new is made of things that
already exist), and writes out a folder with the parts to order and exactly what
to build with them.

There is **no LLM in the retrieval or composition core.** Ranking is real
download counts, stars, and verified-index membership. Decomposition is a
deterministic recipe library. An LLM can *propose* a new decomposition, but the
engine only trusts a component once it's been found in a real registry.

---

## The idea, stated plainly

Everything that gets created is built from things that already exist. So the hard
part of building something new isn't invention, it's **search**: finding the
pieces that already exist and the order to combine them. That search is
multi-step, because a piece you need is itself built from other pieces.

This engine is that search, made mechanical:

```
goal ──decompose──▶ capabilities (subsystems)
        each capability ──resolve──▶ real components, ranked   (npm, PyPI, crates, GitHub, a verified index)
        each software pick ──expand──▶ its real dependency graph  (proof it's built from what exists)
        assemble ──▶ { software to install, parts to order, build steps }
        render ──▶ a build/ folder you can act on
```

## Run it

```bash
cd anything-engine

# Raw component search — the Google-for-buildable-things primitive (hits live registries)
node cli.mjs --search "svg to gcode" --registry crates,npm,pypi

# Show a real dependency graph — "made of things that already exist", verifiable
node cli.mjs --expand crates:svg2gcode --depth 1

# Full build plan for a goal
node cli.mjs "graphic design to hardware"

# ...and write the orderable dossier folder
node cli.mjs "graphic design to hardware" --emit ../builds/graphic-design-to-hardware

# List the recipe library
node cli.mjs --recipes
```

No install step, no dependencies — plain Node ≥18 with global `fetch`.

## What's real vs what's gated (honest)

The engine was first built inside a locked-down sandbox, which shaped an honest
design: it uses **live sources where the network reaches them**, and a **verified
index** for everything else, with real source-adapters that go live the moment
egress or an API key is present.

| Source | Status here | Notes |
| --- | --- | --- |
| `crates` (crates.io) | **live** | full search + real dependency edges |
| `npm` (registry.npmjs.org) | **live** | full search + real dependency edges |
| `pypi` (pypi.org) | **live (name-resolve)** | PyPI retired fuzzy search; resolves exact package names from recipes, returns real metadata + deps |
| `github` | **gated** | real code; needs open egress to api.github.com (+ `GITHUB_API_TOKEN` for rate limit). Falls back to the verified index when blocked. |
| `index` (curated) | **always** | verified parts (with real prices) and repos that live behind a blocked search API |

Set `GITHUB_API_TOKEN` (a public-scope PAT) to turn on live GitHub search.

## How it's built (files)

```
cli.mjs                 the terminal interface (search / expand / plan / emit / recipes)
src/
  engine.mjs            orchestrator: goal -> build plan
  decompose.mjs         goal -> capabilities, via the recipe library (LLM-free)
  resolve.mjs           one capability -> ranked real components across sources
  expand.mjs            a component -> its real dependency graph (BFS, bounded)
  dossier.mjs           a plan -> an orderable build/ folder
  registry.mjs          the set of component sources, keyed by id
  http.mjs              JSON fetch with timeout + honest failure
  sources/
    crates.mjs npm.mjs pypi.mjs   live registries (search + dependency edges)
    github.mjs                    live-or-gated repo search
    index.mjs                     the curated verified catalog
recipes/                *.json — reusable goal decompositions (grows over time)
index/                  *.json — the verified component catalog (parts + repos)
test/                   node --test, network-free core
```

## Extending it

- **New goal** → drop a recipe JSON in `recipes/`. A recipe maps a goal to an
  ordered list of capabilities, each with a search query, the registries to hit,
  and the component `kinds` it wants (`software`, `firmware`, `host-app`, `part`,
  `input-source`).
- **New component source** (Octopart, Thingiverse, a distributor API) → add one
  file under `src/sources/` exposing `search()` (and optionally `deps()`), and
  register it in `registry.mjs`.
- **New verified parts/repos** → add entries to an `index/*.json` file, tagged
  with a `capability` and `keywords`.

## Where this is going

Today the input is a text goal. The roadmap input is **EEG** — brain signal in,
build dossier out — using the open stack that already exists for it (see
`recipes/eeg-to-intent.json` and the `input-source` component kind). Same engine,
a different front door: think it, and the search for how to build it runs itself.
