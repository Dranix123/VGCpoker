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
test('turn notice remains visible and distinguishes narration, other turns and priority',()=>{
  const context={esc:x=>String(x).replaceAll('<','&lt;')};vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function turnNotice('),source.indexOf('function table(')),context);
  const r={seat:0,players:[{name:'你'},{name:'1号',bot:true}]};
  const g={phase:'play',turn:0,finished:[]};
  assert.match(context.turnNotice(r,g),/your-turn.*轮到你出牌/);
  r.audioWaiting=true;assert.match(context.turnNotice(r,g),/播报中.*接下来由你出牌/);
  assert.ok(!context.turnNotice(r,g).includes('your-turn'));
  r.audioWaiting=false;g.turn=1;assert.match(context.turnNotice(r,g),/1号 正在出牌/);
  g.response={};assert.match(context.turnNotice(r,g),/your-turn.*你可以优先管牌/);
  g.negotiation={};assert.match(context.turnNotice(r,g),/等待玩家确认/);
  g.phase='over';assert.equal(context.turnNotice(r,g),'');
});
