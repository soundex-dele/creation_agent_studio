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
    expect(buildTaskRelation(applicationRun, [applicationRun]).map((node) => node.type))
      .toEqual(['application', 'execution']);
  });

  it('opens a conversation task at its exact conversation page', () => {
    const conversationRun = run({
      task_type: 'conversation',
      source_type: 'conversation',
      source_id: 'conversation 42',
      conversation_id: 'conversation 42',
      application_id: '9',
    });

    expect(buildTaskRelation(conversationRun, [conversationRun]).map((node) => node.type))
      .toEqual(['application', 'conversation']);
    expect(taskDestination(conversationRun)).toEqual({
      path: '/chat?conversation=conversation%2042',
      label: '打开对话',
    });
  });

  it('builds automation to workflow to application to conversation', () => {
    const automationRun = run({
      id: 'automation-run',
      task_type: 'automation',
      source_type: 'workflow',
      source_id: '3',
      workflow_id: '3',
      automation_id: 8,
    });
    const conversationRun = run({
      id: 'conversation-run',
      parent_id: automationRun.id,
      task_type: 'conversation',
      source_type: 'workflow_step',
      application_id: '12',
      conversation_id: '33',
    });

    expect(buildTaskRelation(automationRun, [automationRun, conversationRun])
      .map((node) => node.type))
      .toEqual(['automation', 'workflow', 'application', 'conversation']);
  });
});
