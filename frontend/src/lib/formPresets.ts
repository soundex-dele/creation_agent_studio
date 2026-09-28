import type { FormPresetSnapshot, GuidedPrompt, GuidedQuestion } from '@/types';

export type FormAnswers = Record<string, string | string[] | number>;

export function presetSavePolicy(question: GuidedQuestion) {
  if (question.type === 'file' || ['html_path', 'assets', 'output_directory', 'drafts_root', 'file_path'].includes(question.key)) return 'never';
  return question.preset_save || (['source', 'article', 'content', 'topic', 'text', 'material'].includes(question.key) ? 'optional' : 'preference');
}

export function formAnswers(prompt: GuidedPrompt | null, preset: FormPresetSnapshot | null, overrides: FormAnswers): FormAnswers {
  return {
    ...Object.fromEntries((prompt?.questions || []).flatMap((q) => q.default_value == null ? [] : [[q.key, q.default_value as string | string[] | number]])),
    ...(preset?.values || {}), ...overrides,
  };
}

export function presetReference(preset: FormPresetSnapshot | null) {
  return preset ? { kind: preset.kind, id: preset.id } : null;
}

export function formErrorMessage(error: unknown, fallback = '操作失败，请重试。'): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  const messages = (value: unknown): string[] => typeof value === 'string' ? [value]
    : value && typeof value === 'object' ? Object.values(value).flatMap(messages) : [];
  return messages(data).join('；') || fallback;
}
