/** Publish the first update immediately, then only the latest projection per interval.
 * Events must still be reduced in order before scheduling their projections.
 */
export function createStreamUpdates(interval = 80) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending: (() => void) | undefined;

  const tick = () => {
    timer = undefined;
    const update = pending;
    pending = undefined;
    if (update) {
      timer = setTimeout(tick, interval);
      update();
    }
  };

  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    const update = pending;
    pending = undefined;
    update?.();
  };

  return {
    schedule(update: () => void) {
      if (timer !== undefined) {
        pending = update;
      } else {
        timer = setTimeout(tick, interval);
        update();
      }
    },
    flush,
  };
}
