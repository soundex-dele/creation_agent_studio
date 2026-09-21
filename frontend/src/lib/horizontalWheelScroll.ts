export interface HorizontalScrollTarget {
  clientWidth: number;
  scrollLeft: number;
  scrollWidth: number;
}

export interface WheelDelta {
  deltaMode: number;
  deltaX: number;
  deltaY: number;
}

const DOM_DELTA_LINE = 1;
const DOM_DELTA_PAGE = 2;
const LINE_HEIGHT_PX = 16;

/**
 * Converts a predominantly vertical mouse-wheel gesture into horizontal
 * movement. It returns false at either edge so the surrounding page can keep
 * scrolling normally.
 */
export const scrollHorizontalWithWheel = (
  target: HorizontalScrollTarget,
  wheel: WheelDelta,
) => {
  if (wheel.deltaY === 0 || Math.abs(wheel.deltaX) >= Math.abs(wheel.deltaY)) {
    return false;
  }

  const maximumScrollLeft = Math.max(0, target.scrollWidth - target.clientWidth);
  if (maximumScrollLeft === 0) return false;

  const multiplier = wheel.deltaMode === DOM_DELTA_LINE
    ? LINE_HEIGHT_PX
    : wheel.deltaMode === DOM_DELTA_PAGE
      ? target.clientWidth
      : 1;
  const nextScrollLeft = Math.min(
    maximumScrollLeft,
    Math.max(0, target.scrollLeft + wheel.deltaY * multiplier),
  );

  if (nextScrollLeft === target.scrollLeft) return false;
  target.scrollLeft = nextScrollLeft;
  return true;
};
