/** Render incomplete structured model output as readable copy, without exposing
 * JSON punctuation, record identifiers or a transient parse error to the user. */
const labels: Record<string, string> = {
  titles: '候选标题', cover: '封面短句', body: '发布文案', tags: '话题建议', pages: '实拍图排版',
  caption: '上图文字', layout: '排版／户型', script: '口播稿', shots: '镜头建议', checks: '待核实信息',
  topics: '选题计划', title: '标题', angle: '表达角度', date: '日期', answer: '回复与建议',
  questions: '下一步待确认', requirements: '需求草稿', budget_min: '最低预算', budget_max: '最高预算',
  city: '城市', districts: '片区', rental_type: '出租方式', move_in: '入住日期', must_have: '必要条件',
  needs: '生活需求', concerns: '关注点',
};

function partialObject(source: string): unknown {
  let pos = 0;
  const space = () => { while (/\s/.test(source[pos] || '') && pos < source.length) pos++; };
  function readString(): string {
    pos++;
    let result = '';
    while (pos < source.length) {
      const char = source[pos++];
      if (char === '"') break;
      if (char !== '\\') { result += char; continue; }
      const escaped = source[pos++];
      if (escaped === 'u') {
        const hex = source.slice(pos, pos + 4);
        if (!/^[0-9a-f]{4}$/i.test(hex)) break;
        result += String.fromCharCode(parseInt(hex, 16)); pos += 4;
      } else if (escaped) {
        result += ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', '"': '"', '\\': '\\', '/': '/' } as Record<string, string>)[escaped] ?? '';
      }
    }
    return result.replace(/[\uD800-\uDBFF]$/, '');
  }
  function value(depth: number): unknown {
    if (depth > 20) { pos = source.length; return undefined; }
    space();
    const char = source[pos];
    if (char === '"') return readString();
    if (char === '{') {
      pos++; const object: Record<string, unknown> = Object.create(null);
      while (pos < source.length) {
        space(); if (source[pos] !== '"') break;
        const key = readString(); space(); if (source[pos++] !== ':') break;
        object[key] = value(depth + 1); space(); if (source[pos] !== ',') break; pos++;
      }
      space(); if (source[pos] === '}') pos++;
      return object;
    }
    if (char === '[') {
      pos++; const array: unknown[] = [];
      while (pos < source.length) {
        space(); if (source[pos] === ']') break;
        const previous = pos; const item = value(depth + 1);
        if (item !== undefined) array.push(item);
        if (pos === previous) break;
        space(); if (source[pos] !== ',') break; pos++;
      }
      space(); if (source[pos] === ']') pos++;
      return array;
    }
    const token = source.slice(pos).match(/^(true|false|null|-?\d+(?:\.\d+)?)/)?.[0];
    if (token) { pos += token.length; return JSON.parse(token); }
    return undefined;
  }
  return value(0);
}

function readable(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return ({ whole: '整租', shared: '合租' } as Record<string, string>)[value] || value;
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(readable).filter(Boolean).join('\n\n');
  if (typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => {
    if (!Object.prototype.hasOwnProperty.call(labels, key)) return [];
    const text = readable(item);
    return text ? [`${labels[key]}\n${text}`] : [];
  }).join('\n\n');
  return '';
}

export function rentalStreamText(raw: string): string {
  const text = raw.slice(0, 200000);
  const start = text.indexOf('{');
  if (start < 0) return text.replace(/```[^\n]*$/, '').trim();
  const commentary = text.slice(0, start).replace(/```(?:json)?\s*$/i, '').trim();
  return [commentary, readable(partialObject(text.slice(start)))].filter(Boolean).join('\n\n');
}
