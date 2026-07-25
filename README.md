# shortcuts — home base for the anything-engine

> If something can be thought up, it can be built. Everything new is made from
> things that already exist. The bottleneck isn't invention, it's **search**:
> finding the pieces that already exist and the order to combine them.

This repo is the home base for **[anything-engine](./anything-engine/)** — a
search engine for agents that takes a goal for a thing that *doesn't exist yet*,
finds the real, existing components that can be composed to build it, walks the
real dependency graph of what it finds, and emits an orderable build dossier:
the parts to order and exactly what to build with them.

No LLM sits in the retrieval or composition core. It ranks on real download
counts, stars, and a verified index; it decomposes with a deterministic recipe
library; and it only trusts a component once it's been found in a real registry.

## Start here

```bash
cd anything-engine

node cli.mjs "graphic design to hardware"                 # a full build plan
node cli.mjs "graphic design to hardware" --emit ../builds/graphic-design-to-hardware
node cli.mjs --search "svg to gcode" --registry crates,npm,pypi   # raw component search
node cli.mjs --expand crates:svg2gcode                    # a real dependency graph
node cli.mjs --recipes                                     # the recipe library
```

Full docs: **[anything-engine/README.md](./anything-engine/README.md)**.

## What's built

- **[anything-engine/](./anything-engine/)** — the engine (sources, recipes,
  verified index, tests).
- **[flow/](./flow/)** — push-to-talk dictation that replaces Wispr Flow:
  hold a key, speak English/Hindi/Hinglish, and it types the result into the
  frontmost app with human punctuation, choosing Devanagari vs romanized
  Hinglish automatically from who you're talking to. ~$2/month in API costs
  vs Wispr's $15.
- **[builds/](./builds/)** — dossiers the engine has produced. The flagship is
  **[graphic-design-to-hardware](./builds/graphic-design-to-hardware/)**: take a
  2D design and build the machine that turns it into physical motion (pen
  plotter → drag-knife → light diode laser), from software you clone to parts you
  order for ~$130.

## The through-line

The flagship build is one instance. The same engine answers any goal the recipe
library covers, and grows a new capability by dropping in a recipe file or a
component source. The roadmap front door is EEG: think it, and the search for how
to build it runs itself.
