import { describe, expect, it } from 'vitest';
import { routeWorkflowEdge, type WorkflowNodeBounds } from '../workflowEdgeRouting';

const card = (x: number, y: number, width = 236, height = 124): WorkflowNodeBounds => ({ x, y, width, height });

function checkRoute(nodes: WorkflowNodeBounds[], sourceIndex: number, targetIndex: number) {
  const from = nodes[sourceIndex];
  const to = nodes[targetIndex];
  const source = { x: from.x + from.width, y: from.y + from.height / 2 };
  const target = { x: to.x, y: to.y + to.height / 2 };
  const points = routeWorkflowEdge(source, target, nodes);
  expect(points).not.toBeNull();
  expect(points![0]).toEqual(source);
  expect(points![points!.length - 1]).toEqual(target);
  expect(points![1].x).toBeGreaterThan(source.x);
  expect(points![points!.length - 2].x).toBeLessThan(target.x);
  points!.slice(1).forEach((b, index) => {
    const a = points![index];
    expect(a.x === b.x || a.y === b.y).toBe(true);
    nodes.forEach((node) => {
      const crosses = a.y === b.y
        ? a.y > node.y && a.y < node.y + node.height
          && Math.max(a.x, b.x) > node.x && Math.min(a.x, b.x) < node.x + node.width
        : a.x > node.x && a.x < node.x + node.width
          && Math.max(a.y, b.y) > node.y && Math.min(a.y, b.y) < node.y + node.height;
      expect(crosses, `segment ${JSON.stringify([a, b])} crosses ${JSON.stringify(node)}`).toBe(false);
    });
  });
  return points!;
}

describe('workflow edge routing', () => {
  it('routes the writer-to-PNG bypass clear of the illustration card in the parallel preset', () => {
    const nodes = [card(40, 180), card(360, 40), card(680, 40), card(360, 360), card(680, 360)];
    checkRoute(nodes, 0, 2);
    checkRoute(nodes, 0, 1);
    checkRoute(nodes, 0, 3);
    checkRoute(nodes, 1, 2);
  });

  it('detours around intermediate nodes on the same row after automatic layout', () => {
    const points = checkRoute([card(40, 40), card(360, 40), card(680, 40)], 0, 2);
    expect(points.some((point) => point.y <= 24 || point.y >= 180)).toBe(true);
  });

  it('uses current positions and measured sizes after moving or resizing cards', () => {
    checkRoute([card(-300, 100, 260, 160), card(100, 0, 300, 340), card(600, 180, 236, 180)], 0, 2);
    checkRoute([card(-300, 100, 260, 160), card(100, 400, 300, 340), card(600, 180, 236, 180)], 0, 2);
  });

  it('routes backwards and vertically stacked connections around the endpoint cards', () => {
    checkRoute([card(500, 40), card(40, 40), card(40, 260)], 0, 1);
    checkRoute([card(40, 40), card(40, 260)], 0, 1);
  });

  it('allows a standard fallback when overlapping cards obstruct an output port', () => {
    expect(routeWorkflowEdge({ x: 276, y: 102 }, { x: 290, y: 102 }, [card(40, 40), card(290, 40)])).toBeNull();
  });
});
