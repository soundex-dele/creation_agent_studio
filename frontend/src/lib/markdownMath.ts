const protectedMarkdownPattern = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;

function normalizeTextSegment(segment: string): string {
  return segment
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, expression: string) => (
      `\n\n$$\n${expression.trim()}\n$$\n\n`
    ))
    .replace(/\\\(([^\n]*?)\\\)/g, (_match, expression: string) => (
      `$${expression.trim()}$`
    ));
}

/**
 * remark-math uses dollar delimiters. Tutor models also commonly emit the
 * LaTeX-style delimiters \(...\) and \[...\], so normalize those without
 * touching fenced or inline code examples.
 */
export function normalizeMarkdownMath(markdown: string): string {
  return markdown
    .split(protectedMarkdownPattern)
    .map((segment, index) => (index % 2 === 0 ? normalizeTextSegment(segment) : segment))
    .join('');
}
