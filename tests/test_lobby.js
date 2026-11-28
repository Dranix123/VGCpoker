'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('public/app.js','utf8');
function flow(screen,counts={}){
  const context={screen,state:{matchCounts:counts}};vm.createContext(context);
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
test('current player keeps their previous play underneath the in-seat status',()=>{
  const start=source.indexOf('const playStatus=');
  const expression=source.slice(start,source.indexOf('    const own=',start));
  for(const turn of [0,1]){
    const context={g:{phase:'play',turn},s:0,played:{kind:'旧出牌',order:1},playNumber:1,seatPlayCards:play=>play.kind};
    vm.createContext(context);
    const html=vm.runInContext(expression+'\nplayedCards',context);
    assert.equal(html.includes('出牌中...'),turn===0);
    assert.ok(html.includes('旧出牌'));
  }
});
test('single-player priority renders at the responder instead of the next seat',()=>{
  const start=source.indexOf('const playStatus=');
  const expression=source.slice(start,source.indexOf('    const own=',start));
  for(const s of [0,2]){
    const context={g:{phase:'play',turn:2,priorityResponder:0},s,played:null,playNumber:1};
    vm.createContext(context);
    const html=vm.runInContext(expression+'\nplayedCards',context);
    assert.equal(html.includes('优先管牌'),s===0);
    assert.ok(!html.includes('出牌中...'));
  }
});
test('autoplay shows badges and cancellation while removing manual play controls',()=>{
 for(const enabled of [false,true]){
  const players=Array.from({length:4},(_,i)=>({id:i+1,name:String(i),connected:true,autoplay:i===0&&enabled}));
  const r={seat:0,capacity:4,players,rated:true,bubbles:{0:'悲',1:'你能秒我？',2:'你可以来点核',3:'どうぞ。'}};
  const g={mode:'basic',phase:'play',turn:0,finished:[],urgentLast:[],counts:[2,2,2,2],hand:[],scores:[0,0],log:[]};
  const context={state:{user:{id:1}},esc:String,ranks:{},suits:{},selected:new Set(),roomHeading:()=>'',card:()=>'',r,g};vm.createContext(context);
  const html=vm.runInContext(source.slice(source.indexOf('function table('),source.indexOf('function showAuth('))+'\ntable(r,g);',context);
  assert.equal(html.includes('取消托管'),enabled);
  assert.equal(html.includes('class="autoplay-status"'),enabled);
  assert.equal(html.includes('data-action="play"'),!enabled);
  assert.ok(html.includes('data-action="autoplay"'));
  assert.equal((html.match(/class="speech-bubble"/g)||[]).length,4);
  const board=html.slice(html.indexOf('<section class="board"'),html.indexOf('</section>'));
  assert.doesNotMatch(board,/data-player-seat="0"/);
  assert.match(html,/<div class="own-player[^"]*" data-own-seat="0">.*data-player-seat="0"/);
  for(let seat=0;seat<4;seat++)assert.ok(html.includes(`aria-label="${seat}的发言"`));
  assert.ok(!html.includes('table-chat'));
 }
});


test('multiplayer modes show matching counts and room-code spectating',()=>{
 const html=flow('create',{landlord:2,standard:1});
 assert.equal((html.match(/data-action="match"/g)||[]).length,5);
 assert.ok(html.includes('匹配 · 2 个房间'));
 assert.ok(html.includes('匹配 · 1 个房间'));
 assert.ok(html.includes('data-action="watch"'));
 assert.ok(!flow('single').includes('data-action="match"'));
 assert.ok(!flow('single').includes('data-action="watch"'));
});
test('multiplayer creation exposes opt-in matching and spectator settings',()=>{
 for(const screen of ['single','create']){
  let html='';const context={screen,state:{preferences:{}},names:{},esc:String,showModal:(kind,content)=>{html=content;}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function showCreate('),source.indexOf('async function showLeaderboard('))+'\nshowCreate("standard");',context);
  assert.equal(html.includes('name="joinPolicy"'),screen==='create');
  assert.equal(html.includes('name="allowSpectators"'),screen==='create');
  assert.ok(!/<input[^>]*name="allowSpectators"[^>]*checked/.test(html));
 }
});
test('spectator table opens all-hand panel without action controls',()=>{
 const players=Array.from({length:4},(_,i)=>({id:i+1,name:String(i),connected:true}));
 const r={seat:null,spectator:true,capacity:4,players,rated:true};
 const g={mode:'basic',phase:'play',turn:0,finished:[],urgentLast:[],counts:[1,1,1,1],hand:[],scores:[0,0],log:[],
  publicHands:players.map((_,owner)=>({owner,actor:owner,cards:[{rank:owner+4,suit:'S'}]}))};
 const context={state:{user:{id:9}},esc:String,ranks:{4:4,5:5,6:6,7:7},suits:{S:'♠'},selected:new Set(),roomHeading:()=>'',card:()=>'',r,g};vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('function table('),source.indexOf('function showAuth(')),context);
 for(const phase of ['play','over']){
  g.phase=phase;g.winner=[0];const html=vm.runInContext('table(r,g)',context);
  assert.ok(!html.includes('class="hand-area"'));
  assert.ok(!html.includes('data-action="play"'));
  assert.ok(!html.includes('data-action="autoplay"'));
  assert.ok(!html.includes(' · 你'));
  assert.ok(!html.includes('data-own-seat'));
  if(phase==='play'){
   assert.match(html,/data-table-panel="public" open><summary>全员手牌/);
   for(const rank of [4,5,6,7])assert.ok(html.includes(rank+'♠'));
  }
  if(phase==='over'){assert.ok(html.includes('本局结束'));assert.ok(!html.includes('失败'));}
 }
});

test('room setup keeps rule switches available in expandable options and a separate submit area',()=>{
 for(const screen of ['single','create']){
  let html='';const context={screen,state:{preferences:{}},names:{standard:'4A4A4'},esc:String,showModal:(_,content)=>html=content};vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function showCreate('),source.indexOf('\nasync function showLeaderboard('))+'\nshowCreate("standard");',context);
  assert.ok(html.includes('class="room-options"'));
  assert.ok(html.includes('name="tribute"'));assert.ok(html.includes('name="disableAdvancedHui"'));
  assert.ok(html.includes('class="create-submit"'));
  assert.equal(html.includes('data-ai-type hidden'),screen==='create');
  assert.equal(html.includes('name="joinPolicy"'),screen==='create');
 }
});

test('seat reveal previews use only visible hands and keep both twin identities in order',()=>{
 const ctx={esc:String,ranks:{3:'3',9:'9',14:'A'},suits:{S:'♠',H:'♥'}};
 vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function visibleCard('),source.indexOf('function publicHandsPanel(')),ctx);
 const room={players:[{name:'甲'},{name:'乙'}]};
 const game={phase:'play',hand:[{rank:14,suit:'S'}],publicHands:[
  {owner:1,cards:[{rank:3,suit:'H',effective:9}]},{owner:1,cards:[{rank:9,suit:'S'}]}
 ]};
 assert.equal(ctx.seatRevealedHand(room,game,0),'');
 const html=ctx.seatRevealedHand(room,game,1);
 assert.match(html,/手牌 A[\s\S]*3♥→9[\s\S]*手牌 B[\s\S]*9♠/);
 assert.doesNotMatch(html,/A♠/);
 assert.match(ctx.seatRevealedHand({...room,replay:true},game,1),/id="replay-revealed-1"/);
});
