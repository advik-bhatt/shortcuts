// Tests for the deterministic, network-free core of the engine.
// (The live registry sources are exercised by cli.mjs against real APIs; these
// tests cover the logic that must be correct regardless of the network:
// recipe matching, capability-scoped index search, and dossier rendering.)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { decompose, loadRecipes } from '../src/decompose.mjs';
import * as index from '../src/sources/index.mjs';
import { writeDossier } from '../src/dossier.mjs';

test('decompose matches the graphic-design recipe from a loose goal', () => {
  const d = decompose('turn my svg design into a machine that draws it');
  assert.equal(d.matched, true);
  assert.equal(d.recipe, 'graphic design to hardware');
  assert.ok(d.capabilities.length >= 5, 'should have the full subsystem list');
});

test('decompose falls back to a flat search when no recipe matches', () => {
  const d = decompose('zzzq nonsense goal that matches nothing 999');
  assert.equal(d.matched, false);
  assert.equal(d.capabilities.length, 1);
  assert.ok(d.note && d.note.includes('No recipe'));
});

test('recipes on disk are well-formed', () => {
  const rs = loadRecipes();
  assert.ok(rs.length >= 1);
  for (const r of rs) {
    assert.ok(r.goal, `${r._file} has a goal`);
    assert.ok(Array.isArray(r.capabilities) && r.capabilities.length, `${r._file} has capabilities`);
    for (const c of r.capabilities) {
      assert.ok(c.capability && c.query, `${r._file} capability has capability+query`);
    }
  }
});

test('index search scopes to a capability (no cross-stage g-code leak)', async () => {
  // "vpype" is a design-to-toolpath tool tagged with that capability; it must
  // NOT appear when we resolve the firmware stage even though both say g-code.
  const firmware = await index.search('grbl gcode controller firmware', {
    capability: 'motion-controller firmware (runs G-code, drives steppers)',
    kinds: ['firmware', 'software'],
  });
  const names = firmware.components.map((c) => c.name.toLowerCase());
  assert.ok(names.some((n) => n.includes('grbl')), 'grbl should be present');
  assert.ok(!names.some((n) => n.includes('vpype')), 'vpype (toolpath) must not leak into firmware');
});

test('index search returns capability-tagged parts even with low keyword overlap', async () => {
  // The USB/fastener kit barely shares keywords with the electronics query but
  // is tagged for that capability, so it must still surface.
  const elec = await index.search('arduino cnc shield a4988 stepper driver power supply usb', {
    capability: 'electronics (controller board, stepper drivers, power)',
    kinds: ['part'],
  });
  const names = elec.components.map((c) => c.name.toLowerCase());
  assert.ok(names.some((n) => n.includes('usb')), 'the USB/M3 kit should surface via capability tag');
  assert.ok(elec.components.every((c) => c.kind === 'part'), 'a parts stage returns only parts (no firmware kind)');
});

test('writeDossier emits the full folder from a plan', () => {
  const plan = {
    goal: 'test goal',
    generated_from: 'anything-engine',
    decomposition: { matched: true, recipe: 'graphic design to hardware', recipe_file: 'graphic-design-to-hardware.json', domain: 'test', note: null },
    stages: [
      { capability: 'design to toolpath', query: 'svg to gcode', registries: ['crates'], picks: [{ name: 'svg2gcode', kind: 'software', registry: 'crates', what: 'x', source_url: 'https://crates.io/crates/svg2gcode' }], dep_graph: { count: 9, root: 'crates:svg2gcode' }, notes: [] },
    ],
    software: [{ capability: 'design to toolpath', name: 'svg2gcode', registry: 'crates', license: 'MIT', source_url: 'https://crates.io/crates/svg2gcode', what: 'x', popularity: 1 }],
    bom: [{ capability: 'electronics', name: 'Arduino Uno', qty: 1, unit_usd: 12, line_usd: 12, source_url: 'https://store.arduino.cc', verified: true }],
    optional: [{ capability: 'tool head', name: 'Laser', qty: 1, unit_usd: 70, line_usd: 70, source_url: 'https://example.com', optional: true }],
    bom_total_usd: 12,
    missing: [],
  };
  const dir = mkdtempSync(join(tmpdir(), 'dossier-'));
  writeDossier(plan, dir);
  const bom = readFileSync(join(dir, 'bill-of-materials.md'), 'utf8');
  assert.ok(bom.includes('Arduino Uno'));
  assert.ok(bom.includes('Optional upgrades'));
  assert.ok(bom.includes('$12.00'));
  const steps = readFileSync(join(dir, 'build-steps.md'), 'utf8');
  assert.ok(steps.includes('Order the parts'), 'curated build steps render from the recipe');
  assert.ok(steps.includes('Safety'), 'safety section renders');
  const json = JSON.parse(readFileSync(join(dir, 'plan.json'), 'utf8'));
  assert.equal(json.goal, 'test goal');
});
