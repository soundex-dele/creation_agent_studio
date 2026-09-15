/**
 * Pure helpers for the template workflow: extracting processes from a template
 * structure, assembling guided prompts, and resolving agents by slug.
 */
import type { WorkflowField, WorkflowProcess, WorkflowStructure } from '@/types/workflow';

/** A default single "free" process used when a template has no processes defined. */
const FALLBACK_PROCESS: WorkflowProcess = {
  id: 'free',
  name: '自由对话',
  icon: '✨',
  description: '与助手自由交流，完成你的任务',
  mode: 'free',
};

/**
 * Extract the list of processes from a template/project structure.
 * Falls back to a single free-chat process for legacy templates that only
 * carry informational scenes/phases/pages.
 */
export function getProcesses(structure?: WorkflowStructure | null): WorkflowProcess[] {
  const processes = structure?.processes;
  if (Array.isArray(processes) && processes.length > 0) {
    return processes;
  }
  return [{ ...FALLBACK_PROCESS }];
}

/**
 * Assemble a prompt from a guided process's template and the chosen field values.
 * Replaces {fieldId} tokens; values default to the field label or empty.
 */
export function buildPromptFromTemplate(
  process: WorkflowProcess,
  values: Record<string, string | string[] | number>,
): string {
  const template = process.prompt_template?.trim();
  if (!template) {
    return '';
  }
  // Map field id -> field for reference.
  const fieldMap = new Map<string, WorkflowField>();
  (process.fields || []).forEach((f) => fieldMap.set(f.id, f));

  let prompt = template.replace(/\{(\w+)\}/g, (match, key: string) => {
    const raw = values[key];
    if (Array.isArray(raw) && raw.length > 0) return raw.join('、');
    if (raw !== undefined && raw !== null && String(raw).trim()) {
      return String(raw).trim();
    }
    // Empty values (required or not) are dropped; required ones are validated
    // upstream, so by here an empty token just means "user skipped this option".
    const field = fieldMap.get(key);
    if (field) return '';
    return match; // unknown token — leave as-is
  });

  // Collapse lines whose trailing field became empty (e.g. "比例：") and drop
  // now-empty lines, then tidy spacing.
  prompt = prompt
    .split('\n')
    .map((line) => line.replace(/[：:]\s*$/, '').trimEnd())
    .filter((line) => line.trim().length > 0)
    .join('\n')
    .trim();

  return prompt;
}

/** Find an agent id by slug from a loaded agents list. */
export function resolveAgentId(
  slug: string | undefined,
  agents: { slug: string; id: number }[],
): number | undefined {
  if (!slug) return undefined;
  return agents.find((a) => a.slug === slug)?.id;
}
