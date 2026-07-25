// expand() — the recursive, no-LLM proof of the founder's thesis:
// "everything new is made with things that already exist."
// It walks a component's REAL dependency edges from the registry, breadth-first,
// to a bounded depth, returning the graph of existing pieces the pick is built
// from. This is a machine-verifiable composition tree, not a guess.
import { depsFor } from './registry.mjs';

export async function expand(component, { depth = 1, maxNodes = 40 } = {}) {
  const root = { name: component.name, registry: component.registry, version: component.version };
  const nodes = new Map([[`${root.registry}:${root.name}`, { ...root, depth: 0 }]]);
  const edges = [];
  let frontier = [root];

  for (let d = 0; d < depth; d++) {
    const next = [];
    for (const node of frontier) {
      if (nodes.size >= maxNodes) break;
      const r = await depsFor(node);
      if (!r.ok) continue;
      for (const dep of r.deps) {
        const key = `${dep.registry}:${dep.name}`;
        edges.push({ from: `${node.registry}:${node.name}`, to: key, req: dep.req });
        if (!nodes.has(key)) {
          const child = { name: dep.name, registry: dep.registry, depth: d + 1 };
          nodes.set(key, child);
          next.push(child);
          if (nodes.size >= maxNodes) break;
        }
      }
    }
    frontier = next;
    if (!frontier.length) break;
  }

  return {
    root: `${root.registry}:${root.name}`,
    count: nodes.size,
    truncated: nodes.size >= maxNodes,
    nodes: [...nodes.values()],
    edges,
  };
}
