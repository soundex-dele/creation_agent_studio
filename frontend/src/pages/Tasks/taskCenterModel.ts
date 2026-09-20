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
  requestedType?: string,
): TaskDestination | null => {
  // The default action opens this execution's conversation or workflow run.
  // Opening a resource definition is only available when explicitly requested.
  requestedType ??= taskConversationId(run)
    ? 'conversation'
    : run.source_type === 'workflow' || taskType(run) === 'workflow'
      ? 'workflow'
      : '';
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
  name: string;
  type: string;
  run: RunResource;
}

export interface TaskTreeNode {
  run: RunResource;
  children: TaskTreeNode[];
}

const taskTimestamp = (run: RunResource) => run.created_at
  ? Date.parse(run.created_at)
  : 0;

/** Build the parent/child execution hierarchy returned by the Run API. */
export const buildTaskTree = (runs: RunResource[]): TaskTreeNode[] => {
  const nodes = new Map<string, TaskTreeNode>(runs.map((item): [string, TaskTreeNode] => [
    item.id,
    { run: item, children: [] },
  ]));
  const roots: TaskTreeNode[] = [];

  nodes.forEach((node) => {
    const parent = node.run.parent_id ? nodes.get(node.run.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  });

  const sortChildren = (items: TaskTreeNode[]) => {
    items.sort((left, right) => taskTimestamp(left.run) - taskTimestamp(right.run));
    items.forEach((item) => sortChildren(item.children));
  };
  sortChildren(roots);
  roots.sort((left, right) => taskTimestamp(right.run) - taskTimestamp(left.run));
  return roots;
};

export const flattenTaskTree = (nodes: TaskTreeNode[]): RunResource[] => nodes.flatMap(
  (node) => [node.run, ...flattenTaskTree(node.children)],
);

/** Only the direct parent belongs in a task's relationship list. */
export const buildTaskRelation = (
  run: RunResource,
  allRuns: RunResource[],
): TaskRelationNode[] => {
  if (!run.parent_id || run.parent_id === run.id) return [];
  const parent = allRuns.find((item) => item.id === run.parent_id);
  if (!parent) return [];
  const type = sourceRelationType(parent) || taskType(parent);
  const snapshot = parent.definition_snapshot || {};
  const name = type === 'workflow'
    ? snapshot.workflow_name
    : type === 'application'
      ? snapshot.application_name || snapshot.workflow_step_name
      : null;
  return [{
    type,
    run: parent,
    name: String(name || parent.task_title || `父级任务 #${parent.id.slice(0, 8)}`),
  }];
};
