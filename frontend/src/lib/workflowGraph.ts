import type { Workflow, WorkflowStep } from '@/types';

export interface WorkflowNodePosition { x: number; y: number }

/** Longest-path columns keep branches and joins readable regardless of list order. */
export function layoutWorkflowGraph(steps: WorkflowStep[]): Record<string, WorkflowNodePosition> {
  const levels = new Map<string, number>();
  const known = new Set(steps.map((step) => step.key));
  let remaining = [...steps];
  while (remaining.length) {
    const ready = remaining.filter((step) => (step.depends_on || [])
      .every((key) => !known.has(key) || levels.has(key)));
    // Keep legacy invalid graphs inspectable without an infinite loop.
    if (!ready.length) {
      remaining.forEach((step) => levels.set(step.key, 0));
      break;
    }
    ready.forEach((step) => levels.set(step.key, Math.max(0,
      ...(step.depends_on || []).map((key) => (levels.get(key) ?? -1) + 1))));
    const placed = new Set(ready.map((step) => step.key));
    remaining = remaining.filter((step) => !placed.has(step.key));
  }
  const rows = new Map<number, number>();
  return Object.fromEntries(steps.map((step) => {
    const column = levels.get(step.key) || 0;
    const row = rows.get(column) || 0;
    rows.set(column, row + 1);
    return [step.key, { x: column * 320 + 40, y: row * 180 + 40 }];
  }));
}

export function workflowNodePosition(step: WorkflowStep): WorkflowNodePosition | undefined {
  const editor = step.config?._editor as { position?: WorkflowNodePosition } | undefined;
  const position = editor?.position;
  return position && Number.isFinite(position.x) && Number.isFinite(position.y)
    ? { x: position.x, y: position.y } : undefined;
}

export function positionWorkflowNodes(
  steps: WorkflowStep[], positions: Record<string, WorkflowNodePosition>,
): WorkflowStep[] {
  return steps.map((step) => positions[step.key] ? {
    ...step,
    config: {
      ...step.config,
      _editor: {
        ...(step.config?._editor as Record<string, unknown> || {}),
        position: positions[step.key],
      },
    },
  } : step);
}

export function workflowGraphError(steps: WorkflowStep[]): string | undefined {
  const known = new Set(steps.map((step) => step.key));
  if (known.size !== steps.length) return '节点标识不能重复';
  const remaining = new Map(steps.map((step) => [step.key, new Set(step.depends_on || [])]));
  for (const [key, dependencies] of remaining) {
    if (dependencies.has(key)) return '节点不能连接自身';
    if ([...dependencies].some((dependency) => !known.has(dependency))) return '依赖节点不存在';
  }
  while (remaining.size) {
    const ready = [...remaining].filter(([, dependencies]) => !dependencies.size).map(([key]) => key);
    if (!ready.length) return '连线会形成循环依赖，请调整节点连接';
    ready.forEach((key) => remaining.delete(key));
    remaining.forEach((dependencies) => ready.forEach((key) => dependencies.delete(key)));
  }
  return undefined;
}

function referencesStep(binding: unknown, keys: Set<string>): boolean {
  const source = typeof binding === 'string' ? binding
    : binding && typeof binding === 'object' && 'from' in binding ? binding.from : undefined;
  return typeof source === 'string' && [...keys].some((key) => source.startsWith(`steps.${key}.output`));
}

/** Removed edges must not leave mappings waiting for outputs that are no longer dependencies. */
function clearStepReferences(step: WorkflowStep, removed: Set<string>): WorkflowStep {
  if (!removed.size) return step;
  const config = { ...step.config };
  const automation = config.automation as Record<string, unknown> | undefined;
  if (automation?.answers && typeof automation.answers === 'object') {
    config.automation = {
      ...automation,
      answers: Object.fromEntries(Object.entries(automation.answers)
        .filter(([, binding]) => !referencesStep(binding, removed))),
    };
  }
  return {
    ...step, config,
    input_mapping: Object.fromEntries(Object.entries(step.input_mapping || {})
      .filter(([, binding]) => !referencesStep(binding, removed))),
    condition: step.condition?.source === 'dependency' && removed.has(String(step.condition.step))
      ? {} : step.condition,
  };
}

export function updateWorkflowDependencies(
  steps: WorkflowStep[], key: string, dependencies: string[],
): WorkflowStep[] {
  return steps.map((step) => step.key === key ? {
    ...clearStepReferences(step, new Set((step.depends_on || [])
      .filter((dependency) => !dependencies.includes(dependency)))),
    depends_on: [...new Set(dependencies)],
  } : step);
}

export function removeWorkflowStep(steps: WorkflowStep[], key: string): WorkflowStep[] {
  return steps.filter((step) => step.key !== key).map((step, order) => ({
    ...clearStepReferences(step, new Set([key])), order,
    depends_on: (step.depends_on || []).filter((dependency) => dependency !== key),
  }));
}

export function removeWorkflowStepOutputs(
  mapping: Workflow['output_mapping'], key: string,
): NonNullable<Workflow['output_mapping']> {
  return Object.fromEntries(Object.entries(mapping || {})
    .filter(([, binding]) => !referencesStep(binding, new Set([key]))));
}
