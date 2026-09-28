import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react';

export default function Dialog({ title, background, onEscape, children }: {
  title: string; background: RefObject<HTMLDivElement>; onEscape?: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null); const id = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const content = background.current;
    if (content) content.inert = true;
    ref.current?.focus({ preventScroll: true });
    return () => { if (content) content.inert = false; previous?.focus({ preventScroll: true }); };
  }, [background]);
  return <div className="salvager-overlay">
    <section className="salvager-dialog" role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} ref={ref}
      onKeyDown={event => {
        event.stopPropagation();
        if (event.key === 'Escape') { event.preventDefault(); onEscape?.(); }
        if (event.key === 'Tab') {
          const items = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]') ?? []);
          const first = items[0]; const last = items[items.length - 1];
          if (!items.length) { event.preventDefault(); return; }
          if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) { event.preventDefault(); first.focus(); }
        }
      }}>
      <span className="salvager-eyebrow">POCKET SALVAGER · 归航计划</span>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  </div>;
}
