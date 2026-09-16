import type { GuidedPrompt } from '@/types';

export const guidedPromptIdentifier = (
  prompt: Pick<GuidedPrompt, 'id' | 'key'>,
): string => prompt.id || prompt.key;
