import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateSource} from '../validate.mjs';

test('allows frame-driven React/SVG compositions and archived assets',()=>{
  assert.doesNotThrow(()=>validateSource(`import React from 'react'; import {useCurrentFrame, Img} from 'remotion'; import {assets} from './assets'; export default function Animation(){const frame=useCurrentFrame();return <svg><text x={frame}>你好</text></svg>}`));
});
for(const [name,source] of [
  ['arbitrary imports', `import fs from 'node:fs'; export default ()=>null`],
  ['dynamic import', `export default ()=>{import('react');return null}`],
  ['fetch', `export default ()=>{fetch('/secret');return null}`],
  ['global DOM', `export default ()=>window.location`],
  ['HTML injection', `export default ()=><div dangerouslySetInnerHTML={{__html:'hi'}}/>`],
  ['remote image', `export default ()=><img src="https://example.com/p.png"/>`],
  ['CSS animation', `export default ()=><div style={{animation:'spin 1s'}}/>`],
  ['nondeterminism', `export default ()=><div>{Math.random()}</div>`],
]) test(`rejects ${name}`,()=>assert.throws(()=>validateSource(source)));
