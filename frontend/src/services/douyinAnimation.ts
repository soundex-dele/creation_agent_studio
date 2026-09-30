import { newDocument, newScene, type StudioDocument } from './animationProjects';
import type { Script } from './douyinBenchmark';

export interface AnimationDestination { id: number; name: string }

// A scene range describes its duration; the destination arranges scenes in order.
function durationOf(value: string): number | undefined {
  const timestamp = '(?:\\d+:)?\\d+(?:\\.\\d+)?';
  const range = value.trim().match(new RegExp(`^(${timestamp})\\s*(?:秒|s)?\\s*[-–—~～至]\\s*(${timestamp})\\s*(?:秒|s)?$`, 'i'));
  const seconds = (text: string) => text.split(':').reduce((total, part) => total * 60 + Number(part), 0);
  if (range) {
    const length = seconds(range[2]) - seconds(range[1]);
    return length > 0 ? length : undefined;
  }
  const single = value.trim().match(/^(\d+(?:\.\d+)?)\s*(?:秒|s)$/i);
  return single && Number(single[1]) > 0 ? Number(single[1]) : undefined;
}

export function scriptToAnimation(script: Script): { document: StudioDocument; estimated: boolean } {
  const prompt = [
    `从抖音对标创作脚本制作动画，保留原稿事实与表达，按下方分镜制作。`,
    `标题：${script.title}`, `封面短句：${script.cover}`,
    `完整口播稿：\n${script.narration}`, `拍摄清单：\n${script.checklist.join('\n')}`,
  ].join('\n\n');
  if (prompt.length > 16000) throw new Error('脚本正文与拍摄清单超过动画制作的 16000 字符限制，请精简后另存版本再导入。');
  const source = script.scenes.length ? script.scenes : [{ time: '', visual: script.cover, spoken: script.narration }];
  if (source.length > 30) throw new Error('动画制作最多支持 30 个分镜，请拆分脚本后再导入。');
  let estimated = false;
  const scenes = source.map((scene, index) => {
    const duration = durationOf(scene.time);
    if (duration === undefined) estimated = true;
    const frames = Math.max(1, Math.round((duration ?? Math.max(5, Math.ceil(scene.spoken.length / 4))) * 30));
    return { ...newScene(), title: `镜头 ${index + 1}`, body: '', narration: scene.spoken,
      description: [scene.visual, scene.time ? `原脚本时间：${scene.time}` : ''].filter(Boolean).join('\n'), frames };
  });
  const total = scenes.reduce((sum, scene) => sum + scene.frames, 0);
  if (total > 3600) throw new Error(`分镜总时长约 ${Math.ceil(total / 30)} 秒，超过动画制作的 120 秒限制，请拆分或调整脚本时间后再导入。`);
  // A renderable project must last at least five seconds.
  if (total < 150) { scenes[scenes.length - 1].frames += 150 - total; estimated = true; }
  return { document: { ...newDocument(), aspect: '9:16', prompt, scenes }, estimated };
}
