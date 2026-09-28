/** Copy from a user gesture, including HTTP pages without the Clipboard API. */
export async function copyText(text: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch {
    // Some browsers expose the API but reject writes in embedded/restricted pages.
  }

  const activeElement = document.activeElement;
  const inputSelection = activeElement instanceof HTMLTextAreaElement
    || activeElement instanceof HTMLInputElement
    ? { start: activeElement.selectionStart, end: activeElement.selectionEnd,
      direction: activeElement.selectionDirection }
    : null;
  const selection = window.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange())
    : [];
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.readOnly = true;
  textarea.tabIndex = -1;
  // Keep the control selectable without moving the page or opening a keyboard.
  textarea.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;font-size:16px;';
  document.body.appendChild(textarea);
  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    if (!document.execCommand('copy')) {
      throw new Error('Clipboard copy failed');
    }
  } finally {
    textarea.remove();
    if (activeElement instanceof HTMLElement) {
      activeElement.focus({ preventScroll: true });
    }
    if (inputSelection?.start != null && inputSelection.end != null
      && (activeElement instanceof HTMLTextAreaElement || activeElement instanceof HTMLInputElement)) {
      activeElement.setSelectionRange(inputSelection.start, inputSelection.end, inputSelection.direction ?? undefined);
    }
    if (selection) {
      selection.removeAllRanges();
      ranges.forEach(range => selection.addRange(range));
    }
  }
}
