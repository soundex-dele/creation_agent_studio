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
