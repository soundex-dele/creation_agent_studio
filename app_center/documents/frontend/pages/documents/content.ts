import type { JSONContent } from '@tiptap/core';

const supported = new Set(['doc', 'paragraph', 'heading', 'text', 'hardBreak', 'horizontalRule', 'bulletList', 'orderedList', 'listItem', 'blockquote', 'codeBlock', 'table', 'tableRow', 'tableCell', 'tableHeader']);
export function safeLink(href: string) { return /^(https?:\/\/|mailto:)/i.test(href) && ![...href].some((char) => char.charCodeAt(0) <= 32); }

/** Markdown is parsed to a schema tree, never injected into the DOM as HTML. */
export function safeAIContent(node: JSONContent): JSONContent {
  if (!supported.has(node.type || '')) return { type: 'paragraph' };
  const output: JSONContent = { type: node.type };
  if (node.type === 'text') {
    output.text = node.text || ' ';
    output.marks = (node.marks || []).flatMap((mark) => {
      if (['bold', 'italic', 'strike', 'code'].includes(mark.type)) return [{ type: mark.type }];
      if (mark.type === 'link' && safeLink(String(mark.attrs?.href || ''))) return [{ type: 'link', attrs: { href: mark.attrs?.href, target: '_blank', rel: 'noopener noreferrer nofollow' } }];
      return [];
    });
  }
  const attrs = { heading: ['level'], orderedList: ['start', 'type'], codeBlock: ['language'], tableCell: ['colspan', 'rowspan', 'colwidth', 'align'], tableHeader: ['colspan', 'rowspan', 'colwidth', 'align'] }[node.type || ''];
  if (attrs && node.attrs) output.attrs = Object.fromEntries(attrs.filter((key) => key in node.attrs!).map((key) => [key, node.attrs![key]]));
  if (node.content) output.content = node.content.filter((child) => supported.has(child.type || '')).map(safeAIContent);
  return output;
}

export function documentPlainText(node: JSONContent): string {
  if (node.type === 'text') return node.text || '';
  if (node.type === 'hardBreak' || node.type === 'horizontalRule') return '\n';
  return (node.content || []).map(documentPlainText).join(['paragraph', 'heading', 'codeBlock'].includes(node.type || '') ? '' : '\n');
}
