import { describe, expect, it } from 'vitest';

import {
  methodCompletion,
  recommendStudyMethod,
  studyMethodGuides,
} from '../studyMethodology';

describe('study methodology catalog', () => {
  it('provides complete, uniquely addressable guides', () => {
    expect(studyMethodGuides).toHaveLength(6);
    expect(new Set(studyMethodGuides.map((guide) => guide.id)).size).toBe(studyMethodGuides.length);
    studyMethodGuides.forEach((guide) => {
      expect(guide.steps.length).toBeGreaterThanOrEqual(4);
      expect(new Set(guide.steps.map((step) => step.id)).size).toBe(guide.steps.length);
      expect(guide.pitfalls.length).toBeGreaterThanOrEqual(3);
    });
  });

  it('includes the full mistake-book learning loop', () => {
    const guide = studyMethodGuides.find((item) => item.id === 'mistake-book');
    expect(guide?.steps.map((step) => step.id)).toEqual([
      'collect', 'cause', 'redo', 'turning-point', 'spaced-review', 'variant',
    ]);
  });

  it('recommends from learning state and calculates step progress', () => {
    expect(recommendStudyMethod(2, 0)).toBe('mistake-book');
    expect(recommendStudyMethod(0, 3)).toBe('spaced-review');
    expect(recommendStudyMethod(0, 0)).toBe('preview-10');

    const guide = studyMethodGuides[1];
    expect(methodCompletion([guide.steps[0].id, guide.steps[1].id], guide)).toBe(50);
  });
});
