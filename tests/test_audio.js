'use strict';
const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
async function fixture(music={menu:'/menu.mp3',table:'/table.mp3',tension:'/tension.mp3'}, voices={},activate=true) {
  const tracks=[], spoken=[], tones=[], sources=[], acknowledgements=[], events={}, storage={}, frames=new Map();let now=0,id=0;
  class Audio {constructor(src){this.src=src;this.paused=true;this.currentTime=0;this.duration=180;tracks.push(this);}play(){this.paused=false;return Promise.resolve();}pause(){this.paused=true;}addEventListener(){}}
  const node=()=>({gain:{value:0,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},frequency:{value:0},connect(){},disconnect(){},start(){tones.push(this.frequency?.value);},stop(){this.stopped=true;this.onended?.();}});
  class AudioContext {constructor(){this.currentTime=0;this.sampleRate=1000;this.destination={};}resume(){return Promise.resolve();}createGain(){return node();}createOscillator(){return node();}createBiquadFilter(){return node();}createBufferSource(){const source=node();sources.push(source);return source;}decodeAudioData(){return Promise.resolve({decoded:true});}createBuffer(){return {getChannelData:()=>new Float32Array(80)};}}
  const document={hidden:false,body:{classList:{add(){},remove(){}}},addEventListener:(key,fn)=>events[key]=fn};
  const sandbox={Audio,document,window:{AudioContext,speechSynthesis:{cancel(){},getVoices:()=>[{lang:'zh-CN'}],speak:line=>{spoken.push(line);queueMicrotask(()=>line.onend?.());}}},SpeechSynthesisUtterance:class{constructor(text){this.text=text;}},localStorage:{getItem:key=>storage[key],setItem:(key,value)=>storage[key]=value},fetch:async(url,options)=>{if(url==='/api/audio-ack')acknowledgements.push(JSON.parse(options.body));return {ok:true,arrayBuffer:async()=>new ArrayBuffer(1),json:async()=>({music,effects:{},voices})};},performance:{now:()=>now},requestAnimationFrame:fn=>{frames.set(++id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),setTimeout:fn=>{queueMicrotask(fn);},Map,Math,JSON};
  vm.createContext(sandbox);const audio=vm.runInContext(fs.readFileSync('public/audio.js','utf8')+'\ngameAudio;',sandbox);
  await new Promise(resolve=>setImmediate(resolve));if(activate)events.pointerdown();await new Promise(resolve=>setImmediate(resolve));
  function advance(ms){now+=ms;const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(now));}
  return {audio,tracks,spoken,tones,sources,acknowledgements,events,storage,document,advance};
}
function room(counts=[10,10,10,10]){return {code:'123456',matchId:'one',seat:0,game:{phase:'play',counts,initialCounts:[10,10,10,10],seatPlays:[null,null,null,null],winner:[0,2]}};}
test('music shares timeline and crossfades at 30% without restarting either track',async()=>{
  const f=await fixture(),r=room();f.audio.observe(r);f.advance(1500);
  const table=f.tracks.find(t=>t.src==='/table.mp3'),tension=f.tracks.find(t=>t.src==='/tension.mp3');
  assert.equal(table.paused,false);assert.equal(tension.paused,false);assert.equal(table.volume,.4);assert.equal(tension.volume,0);
  table.currentTime=42;tension.currentTime=40;r.game.counts[1]=3;f.audio.observe(r);
  assert.equal(tension.currentTime,42);assert.equal(table.currentTime,42);f.advance(750);assert.equal(table.volume,.2);assert.equal(tension.volume,.2);
  f.advance(750);assert.equal(table.volume,0);assert.equal(tension.volume,.4);
  r.game.counts[1]=4;f.audio.observe(r);f.advance(1500);assert.equal(tension.volume,.4);
  r.game.phase='over';f.audio.observe(r);f.advance(1500);assert.equal(f.tracks.find(t=>t.src==='/menu.mp3').volume,.4);
});
test('missing tension asset retains match music and refresh uses original counts',async()=>{
  const f=await fixture({table:'/table.mp3'});f.audio.observe(room([2,4,5,5]));f.advance(1500);assert.equal(f.tracks[0].volume,.4);
});
test('state polling does not repeat play/pass voices or settlement sounds',async()=>{
  const f=await fixture(),r=room();f.audio.observe(r);const dealt=f.tones.length;f.audio.observe(r);assert.equal(f.tones.length,dealt);
  r.game.seatPlays[1]={order:1,kind:'三带一对',ranks:[6,6,6,8,8]};f.audio.observe(r);assert.equal(f.spoken.at(-1).text,'三带一对');
  const played=f.tones.length;f.audio.observe(r);assert.equal(f.tones.length,played);assert.equal(f.spoken.length,1);
  r.game.seatPlays[2]={order:1,passed:true,kind:'不出',ranks:[]};f.audio.observe(r);assert.equal(f.spoken.at(-1).text,'不出');
  r.game.phase='over';f.audio.observe(r);const won=f.tones.length;assert.ok(won>played);f.audio.observe(r);assert.equal(f.tones.length,won);
});
test('category volumes persist, mute independently, and background playback pauses',async()=>{
  const f=await fixture();f.audio.setVolume('voice',0);f.audio.speak('不出');assert.equal(f.spoken.length,0);
  f.audio.setVolume('effects',0);const count=f.tones.length;await f.audio.effect('click');assert.equal(f.tones.length,count);
  f.audio.setVolume('music',.2);assert.equal(f.tracks[0].volume,.2);assert.equal(JSON.parse(f.storage['paper-poker-audio']).music,.2);
  f.document.hidden=true;f.events.visibilitychange();assert.ok(f.tracks.every(t=>t.paused));
  f.document.hidden=false;f.events.visibilitychange();assert.equal(f.tracks[0].paused,false);
});

test('recorded voice uses activated Web Audio without mobile system speech',async()=>{
  const f=await fixture({}, {pass:'/audio/voices/pass.mp3'});
  const pending=f.audio.speak('不出','pass');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.spoken.length,0);
  assert.equal(f.sources.at(-1).buffer.decoded,true);
  const source=f.sources.at(-1);f.audio.setVolume('voice',0);assert.equal(source.stopped,true);await pending;
  f.audio.setVolume('voice',.5);const next=f.audio.speak('不出','pass');await new Promise(resolve=>setImmediate(resolve));
  f.document.hidden=true;f.events.visibilitychange();assert.equal(f.sources.at(-1).stopped,true);
  await next;assert.equal(typeof f.events.touchend,'function');
});

test('action acknowledgement waits for recorded voice completion and polling does not replay',async()=>{
  const f=await fixture({}, {pass:'/audio/voices/pass.mp3'}),r=room();f.sources.length=0;
  r.audioEvent={id:1,items:[{voice:'pass'}]};f.audio.observe(r);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.acknowledgements.length,0);
  f.audio.observe(r);assert.equal(f.sources.length,1);
  f.sources[0].onended();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.acknowledgements[0].event,1);
  f.audio.observe(r);assert.equal(f.sources.length,1);
  r.audioEvent={id:2,items:[{voice:'pass'},{voice:'pass'}]};f.audio.observe(r);
  await new Promise(resolve=>setImmediate(resolve));f.sources[1].onended();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.acknowledgements.length,1);
  f.sources[2].onended();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.acknowledgements[1].event,2);
});

test('background interruption does not acknowledge unfinished narration',async()=>{
  const f=await fixture({}, {pass:'/audio/voices/pass.mp3'}),r=room();f.sources.length=0;
  r.audioEvent={id:1,items:[{voice:'pass'}]};f.audio.observe(r);
  await new Promise(resolve=>setImmediate(resolve));
  f.audio.speak('preview','pass');assert.equal(f.sources.length,1);
  f.document.hidden=true;f.events.visibilitychange();
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.acknowledgements.length,0);
  f.document.hidden=false;f.audio.observe(r);
  await new Promise(resolve=>setImmediate(resolve));assert.equal(f.sources.length,2);
  f.sources[1].onended();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.acknowledgements.length,1);
});

test('music fade tolerates a frame timestamp preceding its start',async()=>{
 const f=await fixture();f.audio.observe(room());f.advance(-20);
 assert.ok(f.tracks.every(t=>t.volume>=0&&t.volume<=1));
 f.advance(1520);assert.ok(f.tracks.every(t=>t.volume>=0&&t.volume<=1));
});

test('a refreshed page does not claim narration readiness before a user gesture',async()=>{
 const f=await fixture({}, {}, false);
 assert.equal(f.audio.canAnnounce(),false);
 f.events.pointerdown();assert.equal(f.audio.canAnnounce(),true);
 f.document.hidden=true;assert.equal(f.audio.canAnnounce(),false);
 f.document.hidden=false;assert.equal(f.audio.canAnnounce(),true);
});
