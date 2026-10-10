import spec from '../../../backend/app_center/douyin_benchmark/backend/voice_prompt.json';
import type { VoiceContent } from '@/services/douyinResearch';

/** Shared specification is packaged with the backend and bundled into the frontend. */
export function makeVoicePrompt(content: VoiceContent): string {
  const sections = spec.fields.map(([key, label]) => [label, content[key as keyof VoiceContent]]);
  return [...sections, ...spec.sections].map(([label, text]) => `【${label}】\n${text}`).join('\n\n');
}
