import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateSource} from '../validate.mjs';

test('allows frame-driven React/SVG compositions and archived assets',()=>{
  assert.doesNotThrow(()=>validateSource(`import React from 'react'; import {useCurrentFrame, Img} from 'remotion'; import {assets} from './assets'; export default function Animation(){const frame=useCurrentFrame();return <svg><text x={frame}>你好</text></svg>}`));
});
for (const [name, source] of [
  ['typed scene duration', `type Scene={frames:number}; export default function Animation({scene}:{scene:Scene}) {return <div>{scene.frames}</div>}`],
  ['interface duration', `interface Scene {frames:number} export default ({scene}:{scene:Scene})=><div>{scene.frames}</div>`],
  ['destructured duration', `export default ({scene})=>{const {frames}=scene;return <div>{frames}</div>}`],
  ['renamed duration', `export default ({scene})=>{const {frames:duration}=scene;return <div>{duration}</div>}`],
  ['local duration', `export default ({scene})=>{const frames=scene.frames; const data={frames};return <div>{data.frames}</div>}`],
  ['duration argument', `const length=(frames:number)=>frames-1;export default ({scene})=><div>{length(scene.frames)}</div>`],
  ['computed duration property', `export default ({scene})=><div>{scene['frames']}</div>`],
  ['optional duration property', `export default ({scene})=><div>{scene?.frames}</div>`],
  ['layout top property', `export default ()=><div style={{position:'absolute',top:40}}/>`],
  ['data object fields', `export default ()=>{const data={frames:150,parent:null,location:'center',top:20,self:1};return <div>{data.frames}</div>}`],
  ['own property check', `export default ({scene})=><div>{Object.prototype.hasOwnProperty.call(scene, 'title') ? scene.title : ''}</div>`],
  ['modern own property check', `export default ({scene})=><div>{Object.hasOwn(scene, 'title') ? scene.title : ''}</div>`],
  ['array conversion without prototype', `export default ({scene})=><div>{Array.from(scene.title).slice(0, 3).join('')}</div>`],
]) test(`allows ${name}`,()=>assert.doesNotThrow(()=>validateSource(source)));

for(const [name,source] of [
  ['arbitrary imports', `import fs from 'node:fs'; export default ()=>null`],
  ['dynamic import', `export default ()=>{import('react');return null}`],
  ['fetch', `export default ()=>{fetch('/secret');return null}`],
  ['global DOM', `export default ()=>window.location`],
  ['HTML injection', `export default ()=><div dangerouslySetInnerHTML={{__html:'hi'}}/>`],
  ['remote image', `export default ()=><img src="https://example.com/p.png"/>`],
  ['CSS animation', `export default ()=><div style={{animation:'spin 1s'}}/>`],
  ['nondeterminism', `export default ()=><div>{Math.random()}</div>`],
  ['global frames', `export default ()=>frames[0]`],
  ['global top', `export default ()=>top`],
  ['global frames shorthand', `export default ()=>{const data={frames};return null}`],
  ['type property does not bind global', `type Scene={frames:number};export default ()=>frames[0]`],
  ['type alias does not bind global', `type frames=number;export default ()=>frames[0]`],
  ['unrelated local binding', `const helper=(frames)=>frames;export default ()=>frames[0]`],
  ['out-of-scope local binding', `export default ()=>{if(true){const frames=150}return frames[0]}`],
  ['ambient global declaration', `declare const frames:any;export default ()=>frames[0]`],
  ['ambient global function', `declare function frames():any;export default ()=>frames()`],
  ['type-only imported binding', `import type {frames} from 'react';export default ()=>frames[0]`],
  ['type-only import specifier', `import {type frames} from 'react';export default ()=>frames[0]`],
  ['global this frames', `export default function Scene(){return this.frames[0]}`],
  ['aliased global this', `export default function Scene(){const host=this;return host['frames'][0]}`],
  ['window frames', `export default ()=>window.frames[0]`],
  ['computed window frames', `export default ()=>window['frames'][0]`],
  ['global frames destructuring', `export default ()=>{const {frames:other}=self;return null}`],
  ['constructor property', `export default ({scene})=>scene.constructor`],
  ['computed constructor property', `export default ({scene})=>scene['constructor']`],
  ['bare prototype', `export default ()=>Object.prototype`],
  ['custom prototype', `export default ({scene})=>scene.prototype.hasOwnProperty.call(scene, 'title')`],
  ['shadowed Object', `export default ({Object,scene})=>Object.prototype.hasOwnProperty.call(scene, 'title')`],
  ['prototype mutation', `export default ()=>{Object.prototype.title='changed';return null}`],
  ['prototype method mutation', `export default ()=>{Object.prototype.hasOwnProperty.call=()=>true;return null}`],
  ['computed prototype', `export default ()=>Object['prototype']`],
  ['aliased prototype method', `const own=Object.prototype.hasOwnProperty;export default ({scene})=>own.call(scene, 'title')`],
  ['aliased prototype call', `const own=Object.prototype.hasOwnProperty.call;export default ({scene})=>own(scene, 'title')`],
  ['other prototype methods', `export default ({scene})=>Object.prototype.__defineGetter__.call(scene, 'title', ()=>null)`],
  ['prototype check unsafe argument', `export default ()=>Object.prototype.hasOwnProperty.call(window, 'title')`],
  ['prototype check unsafe key', `export default ({scene})=>Object.prototype.hasOwnProperty.call(scene, eval('title'))`],
  ['prototype check spread arguments', `export default ({scene})=>Object.prototype.hasOwnProperty.call(...scene, 'title')`],
  ['nested prototype access', `export default ({scene})=>Object.prototype.hasOwnProperty.call(scene.prototype, 'title')`],
  ['aliased React effect', `import {useEffect as effect} from 'react';export default ()=>{effect(()=>{});return null}`],
]) test(`rejects ${name}`,()=>assert.throws(()=>validateSource(source)));

test('prototype errors identify the generated source location and explain supported replacements',()=>{
  assert.throws(()=>validateSource(`export default ()=>{\n  return Object.prototype;\n}`), error => {
    assert.match(error.message, /Animation\.tsx:2:17/);
    assert.match(error.message, /Object\.hasOwn\(data, key\)/);
    assert.match(error.message, /Array\.from\(value\)/);
    return true;
  });
});
