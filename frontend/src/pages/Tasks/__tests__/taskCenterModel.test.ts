import { describe, expect, it } from 'vitest';
import type { RunResource } from '@/services/applicationRuntime';
import {
  buildTaskRelation,
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
