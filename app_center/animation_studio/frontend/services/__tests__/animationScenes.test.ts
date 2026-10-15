import { describe, expect, it } from 'vitest';
import { newDocument, withScenes, type StudioScene } from '../animationProjects';
const scene = (id: string, frames: number): StudioScene => ({ id, frames, title: id, body: '', narration: '', description: '', assets: [], locked: false, source: '', style: { color: '#ffffff', background: '#000000', font: 'Noto Sans SC' } });
describe('scene timing edits', () => {
  it('moves captions with reordered scenes and retains scene-relative audio', () => {
    const first = scene('a', 300); const second = scene('b', 150);
    const doc = { ...newDocument(), scenes: [first, second], subtitles: [{ start: 310, end: 400, text: 'B' }], audio: [{ asset_id: 'audio', role: 'narration' as const, scene_id: 'b', start: 0, frames: 90, volume: 1 }] };
    const changed = withScenes(doc, [second, first]);
    expect(changed.subtitles).toEqual([{ start: 10, end: 100, text: 'B' }]);
    expect(changed.audio).toEqual(doc.audio);
    expect(withScenes(doc, [first]).subtitles).toEqual([]);
    expect(withScenes(doc, [first]).audio).toEqual([]);
  });
});
