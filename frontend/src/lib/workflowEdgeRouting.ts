import type { WorkflowNodePosition as Point } from './workflowGraph';

export interface WorkflowNodeBounds extends Point { width: number; height: number }

const clearance = 16;
const portOffset = 24;

/** Route right-output to left-input edges around measured cards, including the endpoint cards. */
export function routeWorkflowEdge(source: Point, target: Point, nodes: WorkflowNodeBounds[]): Point[] | null {
  const boxes = nodes.map((node) => ({
    left: node.x - clearance, right: node.x + node.width + clearance,
    top: node.y - clearance, bottom: node.y + node.height + clearance,
  }));
  const start = { x: source.x + portOffset, y: source.y };
  const end = { x: target.x - portOffset, y: target.y };
  const clear = (a: Point, b: Point) => !boxes.some((box) => (
    a.y === b.y
      ? a.y > box.top && a.y < box.bottom
        && Math.max(a.x, b.x) > box.left && Math.min(a.x, b.x) < box.right
      : a.x > box.left && a.x < box.right
        && Math.max(a.y, b.y) > box.top && Math.min(a.y, b.y) < box.bottom
  ));
  if (!clear(start, start) || !clear(end, end)) return null;

  // Most adjacent connections need no search.
  for (const corner of [{ x: end.x, y: start.y }, { x: start.x, y: end.y }]) {
    if (clear(start, corner) && clear(corner, end)) return [source, start, corner, end, target];
  }

  // A rectilinear visibility grid includes every obstacle boundary. A* finds a
  // short path with a bend penalty, and also works after arbitrary node drags.
  const xs = [...new Set([start.x, end.x, ...boxes.flatMap((box) => [box.left, box.right])])].sort((a, b) => a - b);
  const ys = [...new Set([start.y, end.y, ...boxes.flatMap((box) => [box.top, box.bottom])])].sort((a, b) => a - b);
  const columns = xs.length;
  const point = (index: number): Point => ({ x: xs[index % columns], y: ys[Math.floor(index / columns)] });
  const startIndex = ys.indexOf(start.y) * columns + xs.indexOf(start.x);
  const endIndex = ys.indexOf(end.y) * columns + xs.indexOf(end.x);
  const distance = (a: Point, b: Point) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
  // Each point has two states, retaining arrival direction for bend costs.
  const initial = startIndex * 2;
  const costs = new Map<number, number>([[initial, 0]]);
  const previous = new Map<number, number>();
  const pending = [{ state: initial, cost: 0, estimate: distance(start, end) }];
  while (pending.length) {
    pending.sort((a, b) => b.estimate - a.estimate);
    const current = pending.pop()!;
    if (current.cost !== costs.get(current.state)) continue;
    const index = Math.floor(current.state / 2);
    const at = point(index);
    if (index === endIndex) {
      const route: Point[] = [];
      let state: number | undefined = current.state;
      while (state !== undefined) {
        route.push(point(Math.floor(state / 2)));
        state = previous.get(state);
      }
      return [source, ...route.reverse(), target];
    }
    const column = index % columns;
    const row = Math.floor(index / columns);
    const neighbors = [
      column > 0 ? index - 1 : -1, column + 1 < columns ? index + 1 : -1,
      row > 0 ? index - columns : -1, row + 1 < ys.length ? index + columns : -1,
    ];
    for (const next of neighbors) {
      if (next < 0) continue;
      const to = point(next);
      if (!clear(at, to)) continue;
      const direction = at.y === to.y ? 0 : 1;
      const state = next * 2 + direction;
      const cost = current.cost + distance(at, to) + (direction === current.state % 2 ? 0 : 20);
      if (cost >= (costs.get(state) ?? Infinity)) continue;
      costs.set(state, cost);
      previous.set(state, current.state);
      pending.push({ state, cost, estimate: cost + distance(to, end) });
    }
  }
  // Overlapping cards can obstruct the ports entirely; let the editor retain
  // its standard path until the user separates them.
  return null;
}
