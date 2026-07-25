#!/usr/bin/env node
// anything-engine CLI — the search engine for agents, at the terminal.
//
//   anything "graphic design to hardware" --emit ../builds/graphic-design-to-hardware
//   anything --search "svg to gcode" --registry crates,npm
//   anything --expand crates:svg2gcode
//   anything --recipes
//
// The build-plan and search modes hit real component sources live. No LLM.
import { plan } from './src/engine.mjs';
import { resolve } from './src/resolve.mjs';
import { expand } from './src/expand.mjs';
import { loadRecipes } from './src/decompose.mjs';
import { writeDossier } from './src/dossier.mjs';

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) args[key] = true;
      else {
        args[key] = next;
        i++;
      }
    } else {
      args._.push(a);
    }
  }
  return args;
}

const money = (n) => `$${(Math.round((n || 0) * 100) / 100).toFixed(2)}`;

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.recipes) {
    const rs = loadRecipes();
    console.log(`\n${rs.length} recipe(s) loaded:\n`);
    for (const r of rs) {
      console.log(`  ${r.goal}  (${r._file})`);
      for (const c of r.capabilities) console.log(`      - ${c.capability}  [${c.registries || 'all'}]  » ${c.query}`);
      console.log('');
    }
    return;
  }

  if (args.search) {
    const query = typeof args.search === 'string' ? args.search : args._.join(' ');
    const registries = args.registry || 'crates,npm,pypi,github';
    const limit = args.limit ? Number(args.limit) : 6;
    const r = await resolve({ query, registries }, { limit });
    console.log(`\nsearch: "${query}"  [${r.registries.join(', ')}]\n`);
    if (!r.picks.length) console.log('  (no components found)');
    for (const p of r.picks) {
      const tag = p.kind === 'part' ? `${money(p.price_usd)} x${p.qty || 1}` : `${p.registry}${p.popularity ? ` · ${p.popularity.toLocaleString()}` : ''}`;
      console.log(`  ${p.verified ? '✓ ' : '  '}${p.name}  [${tag}]`);
      if (p.what) console.log(`      ${p.what}`);
      if (p.source_url) console.log(`      ${p.source_url}`);
    }
    if (r.notes.length) console.log(`\n  notes: ${r.notes.join(' | ')}`);
    console.log('');
    return;
  }

  if (args.expand) {
    const [registry, ...rest] = String(args.expand).split(':');
    const name = rest.join(':');
    const depth = args.depth ? Number(args.depth) : 1;
    const g = await expand({ name, registry }, { depth });
    console.log(`\ndependency graph of ${g.root} (depth ${depth}): ${g.count} nodes, ${g.edges.length} edges${g.truncated ? ' (truncated)' : ''}\n`);
    for (const n of g.nodes) console.log(`  ${'  '.repeat(n.depth)}${n.registry}:${n.name}`);
    console.log('');
    return;
  }

  const goal = args._.join(' ').trim();
  if (!goal) {
    console.log('usage:');
    console.log('  anything "<goal>" [--emit <dir>] [--per N] [--json]');
    console.log('  anything --search "<query>" [--registry crates,npm,pypi,github] [--limit N]');
    console.log('  anything --expand <registry>:<name> [--depth N]');
    console.log('  anything --recipes');
    process.exit(1);
  }

  const per = args.per ? Number(args.per) : 4;
  const built = await plan(goal, { perCapability: per });

  if (args.json) {
    console.log(JSON.stringify(built, null, 2));
  } else {
    console.log(`\n=== BUILD PLAN: ${built.goal} ===\n`);
    console.log(built.decomposition.matched ? `recipe: ${built.decomposition.recipe}` : `no recipe matched — flat search`);
    console.log('');
    for (const s of built.stages) {
      console.log(`▸ ${s.capability}`);
      for (const p of s.picks) {
        const tag = p.kind === 'part' ? `${money(p.price_usd)} x${p.qty || 1}` : p.registry;
        console.log(`    ${p.verified ? '✓' : '·'} ${p.name}  [${tag}]  ${p.source_url || ''}`);
      }
      if (s.dep_graph && s.dep_graph.count > 1) console.log(`      built from ${s.dep_graph.count - 1}+ existing packages`);
      if (!s.picks.length && s.notes.length) console.log(`    (nothing found: ${s.notes.join(' | ')})`);
      console.log('');
    }
    console.log(`parts: ${built.bom.length} items, ${money(built.bom_total_usd)}   software: ${built.software.length} packages`);
    if (built.missing.length) console.log(`gaps: ${built.missing.map((m) => m.capability).join(', ')}`);
    console.log('');
  }

  if (args.emit) {
    const dir = typeof args.emit === 'string' ? args.emit : `./build-${Date.now()}`;
    const out = writeDossier(built, dir);
    console.log(`dossier written to ${out}`);
  }
}

main().catch((e) => {
  console.error('error:', e.message);
  process.exit(1);
});
