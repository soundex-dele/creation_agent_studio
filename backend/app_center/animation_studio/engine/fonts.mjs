import fs from 'node:fs/promises';
import path from 'node:path';

// Embed only font subsets touched by the composition, with no external font requests.
export async function fontCss(engine, source) {
  const directory = path.join(engine,'node_modules','@fontsource','noto-sans-sc');
  const points = [...new Set([...source + '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'].map(char=>char.codePointAt(0)))];
  let output = '';
  for (const weight of [400,700]) {
    const css = await fs.readFile(path.join(directory,`${weight}.css`),'utf8');
    for (const match of css.matchAll(/@font-face\s*\{([^}]+)\}/g)) {
      const block = match[1];
      const ranges = block.match(/unicode-range:\s*([^;]+)/)?.[1];
      const font = block.match(/url\(\.\/files\/([^)]*\.woff2)\)/)?.[1];
      if (!font || !ranges) continue;
      const covered = ranges.split(',').some(range=>{
        const [start,end] = range.trim().replace(/^U\+/i,'').split('-').map(value=>parseInt(value,16));
        return points.some(point=>point >= start && point <= (end ?? start));
      });
      if (!covered) continue;
      const bytes = await fs.readFile(path.join(directory,'files',font));
      output += `@font-face{font-family:'Noto Sans SC';font-style:normal;font-display:block;font-weight:${weight};src:url(data:font/woff2;base64,${bytes.toString('base64')}) format('woff2');unicode-range:${ranges};}`;
    }
  }
  return output;
}
