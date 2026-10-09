/** Read incomplete JSON strings as plain text; never render model HTML. */
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

function readable(value: unknown, labels: Record<string, string>, values: Record<string, string>): string {
  if (value == null) return '';
  if (typeof value === 'string') return Object.prototype.hasOwnProperty.call(values, value) ? values[value] : value;
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(item => readable(item, labels, values)).filter(Boolean).join('\n\n');
  if (typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => {
    if (!Object.prototype.hasOwnProperty.call(labels, key)) return [];
    const text = readable(item, labels, values);
    return text ? [`${labels[key]}\n${text}`] : [];
  }).join('\n\n');
  return '';
}

export function structuredStreamText(raw: string, labels: Record<string, string>, values: Record<string, string> = {}): string {
  const text = raw.slice(0, 200000);
  const start = text.indexOf('{');
  if (start < 0) return text.replace(/```[^\n]*$/, '').trim();
  const commentary = text.slice(0, start).replace(/```(?:json)?\s*$/i, '').trim();
  return [commentary, readable(partialObject(text.slice(start)), labels, values)].filter(Boolean).join('\n\n');
}
