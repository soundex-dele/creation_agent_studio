import { describe, expect, it } from 'vitest';
import type { RunResource } from '@/services/applicationRuntime';
import {
  buildTaskTree,
  buildTaskRelation,
  collapseConversationRuns,
  taskDestination,
  taskType,
} from '../taskCenterModel';

const run = (overrides: Partial<RunResource>): RunResource => ({
  id: 'run-1',
  organization_id: 'org-1',
  status: 'succeeded',
  version: 1,
  next_event_sequence: 1,
  definition_snapshot: {},
  input: {},
  output_summary: {},
  ...overrides,
});

describe('task center relationships', () => {
  it('builds a task tree and orders workflow steps from earliest to latest', () => {
    const root = run({
      id: 'workflow-root', source_type: 'workflow', created_at: '2026-09-19T08:00:00Z',
    });
    const laterStep = run({
      id: 'later-step', parent_id: root.id, node_key: 'publish',
      source_type: 'workflow_step', created_at: '2026-09-19T08:02:00Z',
    });
    const firstStep = run({
      id: 'first-step', parent_id: root.id, node_key: 'draft',
      source_type: 'workflow_step', created_at: '2026-09-19T08:01:00Z',
    });

    const tree = buildTaskTree([laterStep, root, firstStep]);

    expect(tree).toHaveLength(1);
    expect(tree[0].run.id).toBe(root.id);
    expect(tree[0].children.map((node) => node.run.id))
      .toEqual([firstStep.id, laterStep.id]);
  });

  it('treats all message turns in one conversation as one task', () => {
    const firstTurn = run({
      id: 'conversation-turn-1',
      source_type: 'conversation',
      source_id: '42',
      conversation_id: '42',
      status: 'succeeded',
      created_at: '2026-09-19T08:00:00Z',
    });
    const latestTurn = run({
      id: 'conversation-turn-2',
      source_type: 'conversation',
      source_id: '42',
      conversation_id: '42',
      status: 'running',
      created_at: '2026-09-19T08:05:00Z',
    });

    expect(collapseConversationRuns([firstTurn, latestTurn])).toEqual([latestTurn]);
  });

  it('uses the completed latest answer as the conversation task status', () => {
    const runningTurn = run({
      id: 'conversation-turn-running',
      source_type: 'conversation',
      source_id: '42',
      conversation_id: '42',
      status: 'running',
      created_at: '2026-09-19T08:00:00Z',
    });
    const completedAnswer = run({
      id: 'conversation-turn-completed',
      source_type: 'conversation',
      source_id: '42',
      conversation_id: '42',
      status: 'succeeded',
      created_at: '2026-09-19T08:05:00Z',
    });

    expect(collapseConversationRuns([runningTurn, completedAnswer]))
      .toEqual([completedAnswer]);
  });

  it('does not merge different conversations or non-conversation tasks', () => {
    const conversationOne = run({
      id: 'conversation-1', source_type: 'conversation', source_id: '1',
    });
    const conversationTwo = run({
      id: 'conversation-2', source_type: 'conversation', source_id: '2',
    });
    const workflow = run({
      id: 'workflow-1', source_type: 'workflow', source_id: 'workflow-1',
    });

    expect(collapseConversationRuns([conversationOne, conversationTwo, workflow]))
      .toEqual([conversationOne, conversationTwo, workflow]);
  });

  it('treats an application as a source instead of a task category', () => {
    const applicationRun = run({
      source_type: 'application',
      source_id: '17',
      application_id: '17',
    });

    expect(taskType(applicationRun)).toBe('execution');
    expect(buildTaskRelation(applicationRun, [applicationRun])).toEqual([]);
  });

  it('opens a conversation task in a new window at its exact conversation page', () => {
    const conversationRun = run({
      task_type: 'conversation',
      source_type: 'conversation',
      source_id: 'conversation 42',
      conversation_id: 'conversation 42',
      application_id: '9',
    });

    expect(buildTaskRelation(conversationRun, [conversationRun])).toEqual([]);
    expect(taskDestination(conversationRun)).toEqual({
      path: '/chat?conversation=conversation%2042',
      label: '打开对话',
      target: '_blank',
    });
  });

  it('shows only the direct parent with its workflow name', () => {
    const automationRun = run({
      id: 'automation-run',
      task_type: 'automation',
      source_type: 'workflow',
      source_id: '3',
      workflow_id: '3',
      automation_id: 8,
      task_title: '每天执行',
      definition_snapshot: { workflow_name: '公众号创作流程' },
    });
    const conversationRun = run({
      id: 'conversation-run',
      parent_id: automationRun.id,
      task_type: 'conversation',
      source_type: 'workflow_step',
      application_id: '12',
      conversation_id: '33',
    });

    expect(buildTaskRelation(automationRun, [automationRun, conversationRun])).toEqual([]);
    expect(buildTaskRelation(conversationRun, [automationRun, conversationRun]))
      .toEqual([{ type: 'workflow', name: '公众号创作流程', run: automationRun }]);
  });

  it('excludes grandparents, siblings and children from the parent list', () => {
    const grandparent = run({ id: 'root', source_type: 'workflow' });
    const parent = run({
      id: 'parent', parent_id: grandparent.id, source_type: 'application', source_id: '12',
      task_title: '一段对话标题', definition_snapshot: { application_name: '公众号排版引擎' },
    });
    const current = run({ id: 'current', parent_id: parent.id });
    const sibling = run({ id: 'sibling', parent_id: parent.id });
    const child = run({ id: 'child', parent_id: current.id });
    expect(buildTaskRelation(current, [child, grandparent, sibling, parent, current]))
      .toEqual([{ type: 'application', name: '公众号排版引擎', run: parent }]);
  });

  it('uses the named application step for a workflow-step parent', () => {
    const parent = run({ id: 'parent', source_type: 'workflow_step', definition_snapshot: { workflow_step_name: 'HTML 封面生成器' } });
    const current = run({ parent_id: parent.id });
    expect(buildTaskRelation(current, [parent])[0].name).toBe('HTML 封面生成器');
  });

  it('does not substitute another task when the parent is absent or self-referencing', () => {
    expect(buildTaskRelation(run({ parent_id: 'missing' }), [run({ id: 'other' })])).toEqual([]);
    const current = run({ parent_id: 'run-1' });
    expect(buildTaskRelation(current, [current])).toEqual([]);
  });

  it('opens the current workflow execution even when triggered by automation', () => {
    const current = run({ id: 'current-workflow', parent_id: 'parent-run', task_type: 'automation', source_type: 'workflow', automation_id: 8 });
    expect(taskDestination(current)).toEqual({ path: '/runs/current-workflow', label: '打开工作流任务' });
  });

  it('opens the current application execution conversation instead of its parent or application', () => {
    const current = run({ id: 'current', parent_id: 'parent-workflow', task_type: 'execution', source_type: 'workflow_step', application_id: '9', conversation_id: 'current conversation' });
    expect(taskDestination(current)).toEqual({ path: '/chat?conversation=current%20conversation', label: '打开对话', target: '_blank' });
  });

  it.each([
    { source_type: 'conversation', source_id: 'conversation & 42' },
    { source_type: 'workflow_step', definition_snapshot: { conversation_id: 'conversation & 42' } },
  ])('opens explicit conversation links in new windows using fallback identifiers', (overrides) => {
    const destination = taskDestination(run(overrides), 'conversation');
    expect(destination?.target).toBe('_blank');
    expect(new URL(destination!.path, 'https://studio.test').searchParams.get('conversation'))
      .toBe('conversation & 42');
  });

  it('opens a related parent conversation in a new window', () => {
    const parent = run({ id: 'parent', source_type: 'application', conversation_id: 'parent-chat' });
    const current = run({ id: 'child', parent_id: parent.id, conversation_id: 'child-chat' });
    const [relation] = buildTaskRelation(current, [parent, current]);
    expect(taskDestination(relation.run)).toEqual({
      path: '/chat?conversation=parent-chat', label: '打开对话', target: '_blank',
    });
  });

  it('does not redirect a task without a conversation or workflow to a resource definition', () => {
    expect(taskDestination(run({ task_type: 'automation', source_type: 'application', application_id: '9', automation_id: 8 }))).toBeNull();
  });
});
