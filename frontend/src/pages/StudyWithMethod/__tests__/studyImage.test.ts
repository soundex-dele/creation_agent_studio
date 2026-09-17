import { describe, expect, it } from 'vitest';

import { calculateStudyImageOutput } from '../studyImage';

describe('calculateStudyImageOutput', () => {
  it('limits a full-size phone photo before drawing it to canvas', () => {
    expect(calculateStudyImageOutput(4032, 3024, 0, 100)).toMatchObject({
      width: 2048,
      height: 1536,
    });
  });

  it('accounts for rotation and crop without upscaling', () => {
    expect(calculateStudyImageOutput(4032, 3024, 90, 50)).toMatchObject({
      width: 1512,
      height: 2016,
    });
    expect(calculateStudyImageOutput(800, 600, 0, 100)).toMatchObject({
      width: 800,
      height: 600,
      scale: 1,
    });
  });
});
