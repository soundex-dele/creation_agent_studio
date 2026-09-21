import { describe, expect, it } from 'vitest';
import type { WorkflowStep } from '@/types';
import {
  layoutWorkflowGraph, positionWorkflowNodes, removeWorkflowStep, removeWorkflowStepOutputs,
  updateWorkflowDependencies, workflowGraphError, workflowNodePosition,
} from '../workflowGraph';

const step = (key: string, depends_on: string[] = [], patch: Partial<WorkflowStep> = {}): WorkflowStep => ({
  id: key, key, name: key, order: 0, depends_on,
  config: {}, condition: {}, max_attempts: 1,
  application: { id: 1, application_name: key } as WorkflowStep['application'],
  ...patch,
});

describe('workflow graph editing', () => {
  it('lays out branches and joins by dependency instead of the list order', () => {
    const positions = layoutWorkflowGraph([
      step('join', ['left', 'right']), step('right', ['start']),
      step('start'), step('left', ['start']), step('independent'),
    ]);
    expect(positions.start.x).toBeLessThan(positions.left.x);
    expect(positions.left.x).toBe(positions.right.x);
    expect(positions.left.y).not.toBe(positions.right.y);
    expect(positions.join.x).toBeGreaterThan(positions.right.x);
    expect(positions.independent.x).toBe(positions.start.x);
    expect(new Set(Object.values(positions).map((p) => `${p.x},${p.y}`)).size).toBe(5);
  });

  it('rejects self connections, missing nodes and indirect cycles, but accepts parallel paths', () => {
    const steps = [step('a'), step('b', ['a']), step('c', ['b']), step('d', ['a'])];
    expect(workflowGraphError(steps)).toBeUndefined();
    expect(workflowGraphError(updateWorkflowDependencies(steps, 'a', ['c']))).toContain('循环');
    expect(workflowGraphError(updateWorkflowDependencies(steps, 'a', ['a']))).toContain('自身');
    expect(workflowGraphError(updateWorkflowDependencies(steps, 'a', ['missing']))).toContain('不存在');
    expect(workflowGraphError(updateWorkflowDependencies(steps, 'c', ['b', 'd']))).toBeUndefined();
    expect(steps[0].depends_on).toEqual([]);
    expect(workflowGraphError([])).toBeUndefined();
  });

  it('deduplicates connections and cleans only references to removed dependencies', () => {
    const target = step('c', ['a', 'b'], {
      config: { model: 'keep', automation: { guided_prompt_key: 'write', answers: {
        removed: { from: 'steps.a.output.result' }, kept: { from: 'steps.b.output.result' },
        input: { from: 'workflow.input.text' }, literal: { value: 'steps.a.output.result' },
      } } },
      input_mapping: { text: { from: 'steps.a.output.result' }, image: { from: 'steps.b.output.result' } },
      condition: { source: 'dependency', step: 'a', path: 'result', operator: 'exists' },
    });
    const next = updateWorkflowDependencies([step('a'), step('b'), target], 'c', ['b', 'b']);
    expect(next[2].depends_on).toEqual(['b']);
    expect(next[2].input_mapping).toEqual({ image: { from: 'steps.b.output.result' } });
    expect(next[2].condition).toEqual({});
    expect(next[2].config).toEqual({ model: 'keep', automation: { guided_prompt_key: 'write', answers: {
      kept: { from: 'steps.b.output.result' }, input: { from: 'workflow.input.text' },
      literal: { value: 'steps.a.output.result' },
    } } });
    expect(target.depends_on).toEqual(['a', 'b']);
    expect(target.input_mapping?.text).toBeDefined();
  });

  it('removes a node and its output aliases without changing similarly named nodes', () => {
    const steps = [step('a'), step('a-two'), step('c', ['a', 'a-two'], {
      input_mapping: { old: { from: 'steps.a.output.result' }, keep: { from: 'steps.a-two.output.result' } },
    })];
    const next = removeWorkflowStep(steps, 'a');
    expect(next.map((item) => [item.key, item.order])).toEqual([['a-two', 0], ['c', 1]]);
    expect(next[1].depends_on).toEqual(['a-two']);
    expect(next[1].input_mapping).toEqual({ keep: { from: 'steps.a-two.output.result' } });
    expect(removeWorkflowStepOutputs({
      old: { from: 'steps.a.output.result' }, oldString: 'steps.a.output.result',
      keep: { from: 'steps.a-two.output.result' },
    }, 'a')).toEqual({ keep: { from: 'steps.a-two.output.result' } });
    expect(workflowGraphError(next)).toBeUndefined();
  });

  it('preserves positions and automation settings across serialization and list reordering', () => {
    const original = [step('a', [], { config: { automation: { answers: { text: { value: 'draft' } } } } }), step('b', ['a'])];
    const positioned = positionWorkflowNodes(original, { a: { x: -20, y: 155 }, b: { x: 460, y: 80 } });
    const reloaded: WorkflowStep[] = JSON.parse(JSON.stringify(positioned)).reverse();
    expect(workflowNodePosition(reloaded[1])).toEqual({ x: -20, y: 155 });
    expect(workflowNodePosition(reloaded[0])).toEqual({ x: 460, y: 80 });
    expect(positioned[0].config.automation).toEqual(original[0].config.automation);
    expect(original[0].config._editor).toBeUndefined();
    expect(workflowNodePosition(step('legacy'))).toBeUndefined();
    expect(workflowNodePosition(step('invalid', [], { config: { _editor: { position: { x: null, y: 10 } } } }))).toBeUndefined();
  });

  it('keeps legacy cyclic and missing-dependency workflows inspectable', () => {
    const positions = layoutWorkflowGraph([step('a', ['b']), step('b', ['a']), step('c', ['missing'])]);
    expect(Object.keys(positions)).toHaveLength(3);
    expect(Object.values(positions).every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
  });
});
