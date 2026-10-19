'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('public/app.js','utf8');
function flow(screen){
  const context={screen};vm.createContext(context);
  return vm.runInContext(source.slice(source.indexOf('function flowScreen(){'),source.indexOf('function settingsScreen(){'))+'\nflowScreen();',context);
}
test('single and multiplayer flows expose an unlabeled room-number entrance',()=>{
  for(const screen of ['single','create']){
    const html=flow(screen);
    assert.ok(html.includes('id="join-form"'));
    assert.ok(html.includes('id="join-code"'));
    assert.ok(!html.includes('001255'));
    assert.ok(!html.includes('68686'));
    assert.ok(!html.includes('_alternate'));
  }
});
test('tribute is an unchecked option only for supported modes in either flow',()=>{
  for(const screen of ['single','create'])for(const mode of ['basic','standard','trio','landlord']){
    let html='';const context={screen,mode,state:{preferences:{}},names:{},esc:x=>x,showModal:(kind,content)=>{html=content;}};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('function showCreate('),source.indexOf('\nasync function showLeaderboard('))+'\nshowCreate(mode);',context);
    assert.equal(html.includes('name="tribute"'),['basic','standard'].includes(mode));
    assert.ok(!/<input[^>]*name="tribute"[^>]*\bchecked\b/.test(html));
  }
});

test('advanced rules use unchecked opt-out controls in supported modes',()=>{
  for(const screen of ['single','create'])for(const mode of ['standard','trio','basic','landlord']){
    let html='';const context={screen,mode,state:{preferences:{}},names:{},esc:x=>x,showModal:(kind,content)=>{html=content;}};
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('function showCreate('),source.indexOf('\nasync function showLeaderboard('))+'\nshowCreate(mode);',context);
    for(const name of ['disableAdvancedHui','disableAdvancedDead']){
      assert.equal(html.includes(`name="${name}"`),['standard','trio'].includes(mode));
      assert.ok(!new RegExp(`<input[^>]*name="${name}"[^>]*\\bchecked\\b`).test(html));
    }
  }
});
test('current player replaces their previous play with an in-seat status',()=>{
  const start=source.indexOf('const playedCards=');
  const expression=source.slice(start+'const playedCards='.length,source.indexOf(';\n',start));
  for(const turn of [0,1]){
    const context={g:{phase:'play',turn},s:0,played:turn===0?{kind:'旧出牌'}:null};vm.createContext(context);
    const html=vm.runInContext(expression,context);
    assert.equal(html.includes('出牌中...'),turn===0);
  }
  assert.ok(!source.includes('turnNotice('));
});

test('autoplay shows badges and cancellation while removing manual play controls',()=>{
 for(const enabled of [false,true]){
  const players=Array.from({length:4},(_,i)=>({id:i+1,name:String(i),connected:true,autoplay:i===0&&enabled}));
  const r={seat:0,capacity:4,players,rated:true};
  const g={mode:'basic',phase:'play',turn:0,finished:[],urgentLast:[],counts:[2,2,2,2],hand:[],scores:[0,0],log:[]};
  const context={state:{user:{id:1}},esc:String,ranks:{},suits:{},selected:new Set(),roomHeading:()=>'',card:()=>'',r,g};vm.createContext(context);
  const html=vm.runInContext(source.slice(source.indexOf('function table('),source.indexOf('function showAuth('))+'\ntable(r,g);',context);
  assert.equal(html.includes('取消托管'),enabled);
  assert.equal(html.includes('class="autoplay-status"'),enabled);
  assert.equal(html.includes('data-action="play"'),!enabled);
  assert.ok(html.includes('data-action="autoplay"'));
 }
});
