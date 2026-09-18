import { describe, expect, it } from 'vitest';

import { normalizeMarkdownMath } from '../markdownMath';

describe('normalizeMarkdownMath', () => {
  it('normalizes LaTeX inline and display delimiters for remark-math', () => {
    const source = String.raw`十位有 \(5\) 种选法：\[5 \times 4 = 20\]`;

    expect(normalizeMarkdownMath(source)).toBe(
      '十位有 $5$ 种选法：\n\n$$\n5 \\times 4 = 20\n$$\n\n',
    );
  });

  it('keeps existing dollar-delimited formulas unchanged', () => {
    const source = '概率为 $2/5$。\n\n$$P = \\frac{2}{5}$$';

    expect(normalizeMarkdownMath(source)).toBe(source);
  });

  it('does not rewrite delimiters inside inline or fenced code', () => {
    const source = [
      String.raw`示例：\(x+1\)`,
      '',
      '行内代码：',
      '`\\(not-math\\)`',
      '',
      '```text',
      String.raw`\[not-math\]`,
      '```',
    ].join('\n');
    const result = normalizeMarkdownMath(source);

    expect(result).toContain('示例：$x+1$');
    expect(result).toContain('`\\(not-math\\)`');
    expect(result).toContain('```text\n\\[not-math\\]\n```');
  });
});
