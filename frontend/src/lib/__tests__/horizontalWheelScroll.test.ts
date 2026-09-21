import { describe, expect, it } from 'vitest';
import { scrollHorizontalWithWheel } from '../horizontalWheelScroll';

const scrollTarget = (scrollLeft = 0) => ({
  clientWidth: 300,
  scrollLeft,
  scrollWidth: 900,
});

describe('scrollHorizontalWithWheel', () => {
  it('maps a vertical pixel-wheel gesture to horizontal movement', () => {
    const target = scrollTarget(100);

    expect(scrollHorizontalWithWheel(target, {
      deltaMode: 0,
      deltaX: 0,
      deltaY: 80,
    })).toBe(true);
    expect(target.scrollLeft).toBe(180);
  });

  it('normalizes line-based wheel deltas', () => {
    const target = scrollTarget();

    scrollHorizontalWithWheel(target, { deltaMode: 1, deltaX: 0, deltaY: 3 });

    expect(target.scrollLeft).toBe(48);
  });

  it('lets the surrounding page scroll when the list is already at an edge', () => {
    const start = scrollTarget();
    const end = scrollTarget(600);

    expect(scrollHorizontalWithWheel(start, {
      deltaMode: 0,
      deltaX: 0,
      deltaY: -50,
    })).toBe(false);
    expect(scrollHorizontalWithWheel(end, {
      deltaMode: 0,
      deltaX: 0,
      deltaY: 50,
    })).toBe(false);
  });

  it('leaves native horizontal gestures and non-overflowing lists untouched', () => {
    const target = scrollTarget(100);
    const fittingTarget = { clientWidth: 300, scrollLeft: 0, scrollWidth: 300 };

    expect(scrollHorizontalWithWheel(target, {
      deltaMode: 0,
      deltaX: 40,
      deltaY: 10,
    })).toBe(false);
    expect(scrollHorizontalWithWheel(fittingTarget, {
      deltaMode: 0,
      deltaX: 0,
      deltaY: 40,
    })).toBe(false);
    expect(target.scrollLeft).toBe(100);
  });
});
