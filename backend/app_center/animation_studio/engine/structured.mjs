import fs from 'node:fs/promises';
import path from 'node:path';
import {validateSource} from './validate.mjs';

export const defaultScene = `import React from 'react';
import {AbsoluteFill, Img, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';
import {assets} from './assets';
export default function Scene({scene}) {const f=useCurrentFrame();const {width}=useVideoConfig();return <AbsoluteFill style={{background:scene.style?.background||'#ffffff',padding:width*.065,justifyContent:'center',fontFamily:scene.style?.font||'Noto Sans SC',color:'#151827'}}><div style={{opacity:interpolate(f,[0,12],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'}),transform:'translateY('+interpolate(f,[0,18],[24,0],{extrapolateLeft:'clamp',extrapolateRight:'clamp'})+'px)'}}><div style={{fontSize:width*.05,color:scene.style?.color||'#4f46e5',fontWeight:700,marginBottom:width*.025}}>{scene.title}</div><div style={{fontSize:width*.028,whiteSpace:'pre-wrap',lineHeight:1.6}}>{scene.body}</div>{scene.assets?.[0]&&<Img src={assets[scene.assets[0]]} style={{maxWidth:'80%',maxHeight:width*.27,objectFit:'contain',marginTop:width*.025}}/>}</div></AbsoluteFill>}`;

export async function buildStructured(project, doc) {
  if (doc.schema_version !== 2 || !Array.isArray(doc.scenes) || !doc.scenes.length || doc.scenes.length > 30) throw new Error('Invalid scene document');
  let cursor = 0;
  const starts = {};
  const imports = [];
  const elements = [];
  for (let i=0;i<doc.scenes.length;i++) {
    const scene = doc.scenes[i];
    if (!Number.isInteger(scene.frames) || scene.frames < 1) throw new Error('Invalid scene frames');
    const source = scene.source || defaultScene;
    validateSource(source);
    await fs.writeFile(path.join(project, `scene-${i}.tsx`), source);
    imports.push(`import S${i} from './scene-${i}';`);
    starts[scene.id] = cursor;
    elements.push(`<Sequence from={${cursor}} durationInFrames={${scene.frames}}><S${i} scene={doc.scenes[${i}]}/></Sequence>`);
    cursor += scene.frames;
  }
  if (cursor < 150 || cursor > 3600) throw new Error('Invalid total scene duration');
  const audio = (doc.audio || []).map((track, index) => {
    const start = (starts[track.scene_id] || 0) + (track.start || 0);
    const frames = Math.min(track.frames || cursor-start, cursor-start);
    if (frames <= 0) return '';
    return `<Sequence from={${start}} durationInFrames={${frames}}><Audio src={assets[${JSON.stringify(track.asset_id)}]} startFrom={${track.trim_start || 0}} endAt={${(track.trim_start || 0) + (track.clip_frames || frames)}} loop={${Boolean(track.loop)}} volume={(f)=>${Number(track.volume ?? 1)}*Math.min(1,${track.fade_in ? `f/${track.fade_in}` : '1'},${track.fade_out ? `Math.max(0,(${frames}-f)/${track.fade_out})` : '1'})}/></Sequence>`;
  }).join('');
  // Frame-based editing converts to the portable Caption JSON contract here.
  const captions = (doc.subtitles || []).map(s=>({text:s.text,startMs:s.start/30*1000,endMs:s.end/30*1000,timestampMs:null,confidence:null}));
  const source = `import React from 'react';import {AbsoluteFill,Sequence,Audio,Img,useCurrentFrame} from 'remotion';import {assets} from './assets';${imports.join('\n')}
const doc=${JSON.stringify(doc)};const captions=${JSON.stringify(captions)};
function Captions(){const f=useCurrentFrame();const s=doc.subtitle_style;return s.enabled===false?null:<AbsoluteFill style={{justifyContent:s.position==='top'?'flex-start':s.position==='center'?'center':'flex-end',padding:'5%',pointerEvents:'none'}}>{captions.filter(c=>f/30*1000>=c.startMs&&f/30*1000<c.endMs).map((c,i)=><div key={i} style={{textAlign:'center',fontFamily:s.font,fontSize:s.size,color:s.color,background:'rgba(0,0,0,.65)',padding:12,borderRadius:8,whiteSpace:'pre-wrap'}}>{c.text}</div>)}</AbsoluteFill>}
export default function Animation(){return <AbsoluteFill>${elements.join('')}${audio}<Captions/>{doc.brand?.logo&&<Img src={assets[doc.brand.logo]} style={{position:'absolute',right:'3%',top:'3%',width:'10%',maxHeight:'12%',objectFit:'contain'}}/>}</AbsoluteFill>}`;
  await fs.writeFile(path.join(project,'Animation.tsx'),source);
  return source;
}
