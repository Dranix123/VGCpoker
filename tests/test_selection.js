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
  const f=fixture();f.events.pointerdown(f.event(0,10));f.events.pointerup();await f.events.click(f.event(0,10));
  assert.deepEqual([...f.selected],['0']);
  f.events.pointerdown(f.event(1,36));f.events.pointermove(f.event(3,88));f.events.pointermove(f.event(1,36));f.events.pointerup();await f.events.click(f.event(1,36));
  assert.deepEqual([...f.selected],['0','1','2','3']);
});
test('drag starting on a selected card clears cards; keyboard and touch clicks still work',async()=>{
  const f=fixture();f.selected.add('0');f.selected.add('1');f.events.pointerdown(f.event(0,10));f.events.pointermove(f.event(1,36));f.events.pointerup();await f.events.click(f.event(1,36));
  assert.equal(f.selected.size,0);
  await f.events.click(f.event(2,62,{detail:0}));assert.ok(f.selected.has('2'));
  f.events.pointerdown(f.event(3,88,{pointerType:'touch'}));await f.events.click(f.event(3,88));assert.ok(f.selected.has('3'));
});
