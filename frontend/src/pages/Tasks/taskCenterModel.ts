import type { RunResource } from '@/services/applicationRuntime';

export type PrimaryTaskType = 'automation' | 'workflow' | 'conversation';

export const primaryTaskTypes: PrimaryTaskType[] = [
  'automation', 'workflow', 'conversation',
];

export const taskConversationId = (run: RunResource): string | null => {
  if (run.conversation_id) return String(run.conversation_id);
  if (run.source_type === 'conversation' && run.source_id) return String(run.source_id);
  const value = run.definition_snapshot?.conversation_id;
  return value ? String(value) : null;
};

/**
 * A conversation is one user-facing task even though every message turn has
 * its own durable Run. Keep the newest Run as the conversation task's current
 * state so a completed answer resolves the task to `succeeded`.
 */
export const collapseConversationRuns = (runs: RunResource[]): RunResource[] => {
  const collapsed: RunResource[] = [];
  const conversationIndexes = new Map<string, number>();

  runs.forEach((run) => {
    const conversationId = taskConversationId(run);
    if (!conversationId) {
      collapsed.push(run);
      return;
    }

    const existingIndex = conversationIndexes.get(conversationId);
    if (existingIndex === undefined) {
      conversationIndexes.set(conversationId, collapsed.length);
      collapsed.push(run);
      return;
    }

    const existing = collapsed[existingIndex];
    const existingCreatedAt = existing.created_at
      ? Date.parse(existing.created_at)
      : Number.NEGATIVE_INFINITY;
    const candidateCreatedAt = run.created_at
      ? Date.parse(run.created_at)
      : Number.NEGATIVE_INFINITY;
    if (candidateCreatedAt > existingCreatedAt) collapsed[existingIndex] = run;
  });

  return collapsed;
};

export const taskType = (run: RunResource) => {
  const explicit = run.task_type;
  if (explicit && explicit !== 'application') return explicit;
  if (run.source_type === 'workflow_step') {
    return taskConversationId(run) ? 'conversation' : 'execution';
  }
  if (run.source_type === 'application' || explicit === 'application') return 'execution';
  return run.source_type || 'execution';
};

export const taskApplicationId = (run: RunResource): string | null => {
  if (run.application_id) return String(run.application_id);
  if (run.source_type === 'application' && run.source_id) return String(run.source_id);
  const value = run.definition_snapshot?.application_id;
  return value ? String(value) : null;
};

export const taskWorkflowId = (run: RunResource): string | null => {
  if (run.workflow_id) return String(run.workflow_id);
  if (run.source_type === 'workflow' && run.source_id) return String(run.source_id);
  const value = run.definition_snapshot?.workflow_id;
  return value ? String(value) : null;
};

export const sourceRelationType = (run: RunResource): PrimaryTaskType | 'application' | null => {
  if (run.source_type === 'workflow' || run.source_type === 'application'
    || run.source_type === 'conversation') return run.source_type;
  if (run.source_type === 'workflow_step') return 'application';
  return null;
};

export interface TaskDestination {
  path: string;
  label: string;
}

export const taskDestination = (
  run: RunResource,
  requestedType = taskType(run),
): TaskDestination | null => {
  if (requestedType === 'automation' && run.automation_id) {
    return { path: `/automations/${run.automation_id}`, label: '打开自动化' };
  }
  if (requestedType === 'conversation') {
    const conversationId = taskConversationId(run);
    return conversationId
      ? { path: `/chat?conversation=${encodeURIComponent(conversationId)}`, label: '打开对话' }
      : null;
  }
  if (requestedType === 'workflow') {
    return { path: `/runs/${run.id}`, label: '打开工作流任务' };
  }
  if (requestedType === 'application') {
    const applicationId = taskApplicationId(run);
    return applicationId
      ? { path: `/applications/${encodeURIComponent(applicationId)}/run?entry=apps`, label: '打开应用' }
      : null;
  }
  return null;
};

export interface TaskRelationNode {
  type: string;
  run: RunResource;
}

/** Build a compact type chain such as 自动化 → 工作流 → 应用 → 对话. */
export const buildTaskRelation = (
  run: RunResource,
  allRuns: RunResource[],
): TaskRelationNode[] => {
  const byId = new Map(allRuns.map((item) => [item.id, item]));
  const byParent = new Map<string, RunResource[]>();
  allRuns.forEach((item) => {
    if (!item.parent_id) return;
    byParent.set(item.parent_id, [...(byParent.get(item.parent_id) || []), item]);
  });
  const lineage: RunResource[] = [];
  const seenRunIds = new Set<string>();
  let cursor: RunResource | undefined = run;
  while (cursor && !seenRunIds.has(cursor.id)) {
    lineage.unshift(cursor);
    seenRunIds.add(cursor.id);
    cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
  }

  const nodes: TaskRelationNode[] = [];
  const seenTypes = new Set<string>();
  const add = (type: string | null, item: RunResource) => {
    if (!type || seenTypes.has(type)) return;
    seenTypes.add(type);
    nodes.push({ type, run: item });
  };
  const visit = (item: RunResource) => {
    const type = taskType(item);
    if (type !== 'automation' && taskApplicationId(item)) add('application', item);
    add(type, item);
    if (type === 'automation') add(sourceRelationType(item), item);
    (byParent.get(item.id) || []).forEach(visit);
    if (type !== 'conversation' && taskConversationId(item)) add('conversation', item);
  };

  lineage.forEach((item, index) => {
    if (index === lineage.length - 1) visit(item);
    else {
      add(taskType(item), item);
      if (taskType(item) === 'automation') add(sourceRelationType(item), item);
    }
  });
  return nodes;
};
