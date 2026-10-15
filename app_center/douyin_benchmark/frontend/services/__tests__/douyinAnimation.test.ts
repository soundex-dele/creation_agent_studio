import { describe, expect, it } from 'vitest';
import { scriptToAnimation } from '../douyinAnimation';
import type { Script } from '../douyinBenchmark';

const script: Script = { title: '读书的方法', cover: '先提出问题', narration: '完整口播正文', checklist: ['准备道具'], scenes: [
  { time: '0–5秒', visual: '书本展开', spoken: '开场口播' },
  { time: '00:05–00:12', visual: '问题卡片', spoken: '第二段口播' },
] };

describe('Douyin script to animation', () => {
  it('retains the selected production format and does not turn silent shots into spoken instructions', () => {
    const { document } = scriptToAnimation({ ...script, production_format: 'animation', scenes: [{ time: '0–5秒', visual: '标题淡入', spoken: '' }] });
    expect(document.prompt).toContain('原脚本视频形式：动画演示');
    expect(document.scenes[0].narration).toBe('');
    expect(document.scenes[0].description).toContain('标题淡入');
  });
  it('preserves script content and converts time ranges into ordered editable scenes', () => {
    const { document, estimated } = scriptToAnimation(script);
    expect(estimated).toBe(false);
    expect(document.aspect).toBe('9:16');
    expect(document.scenes.map(scene => scene.frames)).toEqual([150, 210]);
    expect(document.scenes.map(scene => scene.narration)).toEqual(script.scenes.map(scene => scene.spoken));
    expect(document.scenes[0].description).toContain('书本展开');
    expect(document.scenes.every(scene => !scene.locked && !scene.source && !scene.assets.length)).toBe(true);
    expect(new Set(document.scenes.map(scene => scene.id)).size).toBe(2);
    for (const text of [script.title, script.cover, script.narration, ...script.checklist]) expect(document.prompt).toContain(text);
    expect(script.scenes[0].time).toBe('0–5秒');
  });

  it('estimates missing timing and uses full narration if there are no scenes', () => {
    const { document, estimated } = scriptToAnimation({ ...script, scenes: [] });
    expect(estimated).toBe(true);
    expect(document.scenes).toHaveLength(1);
    expect(document.scenes[0].narration).toBe(script.narration);
    expect(document.scenes[0].frames).toBeGreaterThanOrEqual(150);
  });

  it('rejects oversized projects rather than silently removing content or compressing timing', () => {
    expect(() => scriptToAnimation({ ...script, scenes: Array(31).fill(script.scenes[0]) })).toThrow('30 个分镜');
    expect(() => scriptToAnimation({ ...script, scenes: [{ ...script.scenes[0], time: '0–121秒' }] })).toThrow('120 秒');
    expect(() => scriptToAnimation({ ...script, narration: '字'.repeat(16000) })).toThrow('16000 字符');
  });

  it('supports decimal durations and pads very short projects to the rendering minimum', () => {
    const { document, estimated } = scriptToAnimation({ ...script, scenes: [{ ...script.scenes[0], time: '1.5秒' }] });
    expect(document.scenes[0].frames).toBe(150);
    expect(estimated).toBe(true);
  });

});
