'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function fixture(){
  const events={},selected=new Set(),cards=Array.from({length:4},(_,i)=>({dataset:{card:String(i)},closest(){return this;}}));
  const document={addEventListener:(name,fn)=>events[name]=fn,elementFromPoint:(x,y)=>y>=0&&y<=100?cards[Math.floor(x/26)]||null:null};
  const sandbox={document,selected,selectionUpdate(){},Set,Math};vm.createContext(sandbox);
  const source=fs.readFileSync('public/app.js','utf8');
  vm.runInContext(source.slice(source.indexOf('let cardSweep='),source.indexOf(' const b=e.target.closest',source.indexOf('let cardSweep=')))+'});',sandbox);
  const event=(index,x,extra={})=>({pointerType:'mouse',pointerId:1,button:0,buttons:1,clientX:x,clientY:50,target:cards[index],detail:1,preventDefault(){},...extra});
  return {events,selected,cards,event};
}
test('mouse click selects once and a fast drag visits every crossed card once',async()=>{
  const f=fixture();f.events.pointerdown(f.event(0,10));f.events.pointerup(f.event(0,10));await f.events.click(f.event(0,10));
  assert.deepEqual([...f.selected],['0']);
  f.events.pointerdown(f.event(1,36));f.events.pointermove(f.event(3,88));f.events.pointermove(f.event(1,36));f.events.pointerup(f.event(0,10));await f.events.click(f.event(1,36));
  assert.deepEqual([...f.selected],['0','1','2','3']);
});
test('drag starting on a selected card clears cards; keyboard and touch clicks still work',async()=>{
  const f=fixture();f.selected.add('0');f.selected.add('1');f.events.pointerdown(f.event(0,10));f.events.pointermove(f.event(1,36));f.events.pointerup(f.event(0,10));await f.events.click(f.event(1,36));
  assert.equal(f.selected.size,0);
  await f.events.click(f.event(2,62,{detail:0}));assert.ok(f.selected.has('2'));
  f.events.pointerdown(f.event(3,88,{pointerType:'touch'}));await f.events.click(f.event(3,88));assert.ok(f.selected.has('3'));
});

test('touch swipe selects and clears cards without a second click toggle',async()=>{
 const f=fixture(),touch=(index,x,extra={})=>f.event(index,x,{pointerType:'touch',...extra});
 f.events.pointerdown(touch(0,10));f.events.pointermove(touch(3,88,{buttons:0}));f.events.pointerup(touch(3,88));
 await f.events.click(touch(3,88,{detail:0}));assert.deepEqual([...f.selected],['0','1','2','3']);
 f.events.pointerdown(touch(0,10));f.events.pointermove(touch(3,88));f.events.pointerup(touch(3,88));
 await f.events.click(touch(3,88));assert.equal(f.selected.size,0);
});
test('secondary touches do not replace a swipe and cancellation ends it',()=>{
 const f=fixture();f.events.pointerdown(f.event(0,10,{pointerType:'touch'}));
 f.events.pointerdown(f.event(3,88,{pointerType:'touch',pointerId:2,isPrimary:false}));
 f.events.pointerup(f.event(3,88,{pointerId:2}));f.events.pointermove(f.event(1,36,{pointerType:'touch'}));
 assert.deepEqual([...f.selected],['0','1']);
 f.events.pointercancel(f.event(1,36));f.events.pointermove(f.event(3,88,{pointerType:'touch'}));
 assert.deepEqual([...f.selected],['0','1']);
});

test('play and pass respect turn, priority window and free lead while preserving selected cards',()=>{
 const source=fs.readFileSync('public/app.js','utf8');
 const fn=source.slice(source.indexOf('function selectionUpdate(){'),source.indexOf('let cardSweep='));
 for(const scenario of ['other-turn','own-turn','free-lead','priority-response','other-clock']){
  const play={},pass={},g={mode:'basic',phase:'play',turn:scenario==='other-turn'?1:0,last:{},lastSeat:1,response:scenario==='priority-response'?{}:null};
  if(scenario==='priority-response')g.turn=1;
  if(scenario==='free-lead')g.last=null;
  if(scenario==='other-clock')g.priorityClock={seat:1};
  const ctx={state:{room:{mode:'basic',seat:0,game:g,players:[{}]}},selected:new Set(['card']),$:s=>s==='[data-action="play"]'?play:s==='[data-action="pass"]'?pass:null,$$:()=>[],Node:{TEXT_NODE:3}};
  vm.createContext(ctx);vm.runInContext(fn+'selectionUpdate();',ctx);
  assert.equal(!!play.disabled,['other-turn','other-clock'].includes(scenario),scenario);
  assert.equal(!!pass.disabled,['other-turn','other-clock','free-lead'].includes(scenario),scenario);
  assert.equal(ctx.selected.size,1);
 }
});
