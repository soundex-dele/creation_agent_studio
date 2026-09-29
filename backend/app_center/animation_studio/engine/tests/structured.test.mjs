import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {buildStructured, defaultScene} from '../structured.mjs';
import {validateSource} from '../validate.mjs';

test('independent scenes keep exact source and compose explicit frame offsets', async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'animation-scenes-'));
  try {
    const doc={schema_version:2,scenes:[{id:'one',frames:150,source:defaultScene},{id:'two',frames:300,source:defaultScene}],audio:[],subtitles:[],subtitle_style:{},brand:{}};
    const source=await buildStructured(dir,doc);
    assert.equal(await fs.readFile(path.join(dir,'scene-0.tsx'),'utf8'),defaultScene);
    assert.match(source,/from=\{150\} durationInFrames=\{300\}/);
    validateSource(defaultScene);
  } finally {await fs.rm(dir,{recursive:true,force:true});}
});
test('structured path still rejects generated network or arbitrary imports', async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'animation-validation-'));
  try { await assert.rejects(buildStructured(dir,{schema_version:2,scenes:[{id:'bad',frames:300,source:"import fs from 'node:fs';export default function Scene(){return null}"}]}),/只允许导入/); }
  finally {await fs.rm(dir,{recursive:true,force:true});}
});

test('typed scene duration survives structured composition and TSX bundling', async()=>{
  const {build}=await import('esbuild');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'animation-typed-scene-'));
  try {
    const source=`import React from 'react';type Scene={frames:number};export default function Scene({scene}:{scene:Scene}){const {frames}=scene;return <div style={{top:20}}>{frames}</div>}`;
    await buildStructured(dir,{schema_version:2,scenes:[{id:'typed',frames:150,source}],audio:[],subtitles:[],subtitle_style:{enabled:false},brand:{}});
    await fs.writeFile(path.join(dir,'assets.ts'),'export const assets = {};');
    const result=await build({entryPoints:[path.join(dir,'Animation.tsx')],bundle:true,write:false,external:['react','remotion'],jsx:'automatic'});
    assert.ok(result.outputFiles[0].text.includes('frames'));
    assert.equal(await fs.readFile(path.join(dir,'scene-0.tsx'),'utf8'),source);
  } finally {await fs.rm(dir,{recursive:true,force:true});}
});

test('own-property checks survive structured composition without changing generated source', async()=>{
  const {build}=await import('esbuild');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'animation-own-property-'));
  try {
    const source=`export default function Scene({scene}){return <div>{Object.prototype.hasOwnProperty.call(scene, 'title') ? scene.title : '动画'}</div>}`;
    await buildStructured(dir,{schema_version:2,scenes:[{id:'own',title:'属性检查',frames:150,source}],audio:[],subtitles:[],subtitle_style:{enabled:false},brand:{}});
    await fs.writeFile(path.join(dir,'assets.ts'),'export const assets = {};');
    const result=await build({entryPoints:[path.join(dir,'Animation.tsx')],bundle:true,write:false,external:['react','remotion'],jsx:'automatic'});
    assert.ok(result.outputFiles[0].text.includes('hasOwnProperty.call'));
    assert.equal(await fs.readFile(path.join(dir,'scene-0.tsx'),'utf8'),source);
  } finally {await fs.rm(dir,{recursive:true,force:true});}
});
