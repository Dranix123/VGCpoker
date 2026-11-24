'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('public/conveyor.js','utf8');
function context(extra={}){
 const skills=[{id:'twins',name:'如影随形',group:3,deal:14,keep:14,text:'两个独立玩家'},{id:'balance',name:'转换',group:0,deal:7,keep:7,text:'弃置再发牌'}];
 const ctx={state:{user:{id:1},features:{conveyorSkills:skills}},esc:String,ranks:{3:'3',4:'4',5:'5',13:'K',14:'A',18:'急'},suits:{S:'♠',H:'♥',C:'♣',D:'♦'},selected:new Set(),roomHeading:()=>'',card:c=>`<button data-card="${c.id}">${c.rank}</button>`,document:{addEventListener:()=>{}},...extra};
 vm.createContext(ctx);const app=fs.readFileSync('public/app.js','utf8');vm.runInContext(app.slice(app.indexOf('function showHandButton'),app.indexOf('function showAuth(')),ctx);vm.runInContext(source,ctx);return ctx;
}
function table(spectator=false,autoplay=false,extra={},conveyorExtra={}){
 const players=Array.from({length:4},(_,i)=>({id:i+1,name:'玩家'+i,skill:i===0?'twins':'balance',autoplay:i===0&&autoplay}));
 const actors=Array.from({length:5},(_,i)=>({id:i,owner:i<2?0:i-1,name:'分身'+i,count:2,resources:{},skill:i<2?'twins':'balance'}));
 const c={actor:0,turnActor:1,skill:'twins',actors,pile:50,discard:4,resources:{money:0,blood:0},zone:[],boundHands:[],choice:null};
 const r={seat:spectator?null:0,players,spectator},g={conveyor:c,phase:'play',finished:[],turn:0,hand:[{id:'own',rank:4,suit:'S'}],scores:[0,0,0,0],log:[],main:3};
 Object.assign(c,conveyorExtra);Object.assign(g,extra);const ctx=context({r,g});return vm.runInContext('conveyorTable(r,g)',ctx);
}
test('conveyor creation exposes opt-in DLC, default recycling and skill bans',()=>{
 const html=vm.runInContext('conveyorCreateOptions()',context());
 assert.equal((html.match(/name="skillDlc"/g)||[]).length,5);
 assert.ok(!html.includes('name="recycle"'));
 assert.ok(html.includes('name="disabledSkills"'));
});
test('four visible seats render five independent actor play areas',()=>{
 const html=table();
 assert.equal((html.match(/class="seat /g)||[]).length,4);
 assert.equal((html.match(/class="actor-play /g)||[]).length,5);
 assert.ok(!html.includes('第 1 手'));assert.ok(!html.includes('第 2 手'));
 assert.ok(html.includes('手牌 A'));assert.ok(html.includes('手牌 B'));
 assert.ok(html.includes('出牌中...'));
});
test('opponents’ skills open a read-only description from the table',async()=>{
 assert.match(table(),/data-action="cv-skill-info" data-skill="balance" aria-label="查看 玩家1 的技能：转换"/);
 let click,modal;
 const ctx=context({document:{addEventListener:(event,fn)=>{if(event==='click')click=fn;}},showModal:(_,html)=>{modal=html;}});
 ctx.state.room={game:{conveyor:{}}};
 const button={dataset:{action:'cv-skill-info',skill:'balance'}};
 await click({target:{closest:()=>button}});
 assert.match(modal,/弃置再发牌/);
 assert.match(modal,/关闭/);
 assert.doesNotMatch(modal,/cv-skill-select/);
 ctx.state.room.game=null;
 await click({target:{closest:()=>button}});
 assert.match(modal,/cv-skill-select/);
});
test('opening hand selection is marked as selection rather than confirmation',()=>{
 const html=table(false,false,{phase:'draft',reveals:[],ready:[]});
 assert.ok(html.includes('选牌中...'));
 assert.ok(!html.includes('等待确认...'));
});
test('conveyor spectators get no hand, target choices or gameplay controls',()=>{
 const html=table(true);
 assert.ok(!html.includes('data-card="own"'));assert.ok(!html.includes('data-action="play"'));assert.ok(!html.includes('data-action="autoplay"'));
});
test('autoplay keeps a visible state and hides ordinary action controls',()=>{
 const html=table(false,true);
 assert.ok(html.includes('托管中'));assert.ok(html.includes('取消托管'));assert.ok(!html.includes('data-action="play"'));
});
test('top-deck ordering preserves the order selected by the user',()=>{
 const ctx=context({q:{kind:'stars',seat:0,title:'观星',cards:[{id:'a',rank:3,suit:'S'},{id:'b',rank:4,suit:'H'}]},c:{skill:'stars',actor:0,actors:[]}});
 vm.runInContext('conveyorChoice(q,c);conveyorChosen=["b","a"];',ctx);
 const html=vm.runInContext('conveyorChoice(q,c)',ctx);
 assert.ok(html.includes('4♥ → 3♠'));
});

test('choice cards select without submitting the form',()=>{
 const ctx=context({q:{kind:'clean-main',seat:0,title:'净牌',cards:[{id:'a',rank:3,suit:'S'}]},c:{skill:'clean',actor:0,actors:[]}});
 const html=vm.runInContext('conveyorChoice(q,c)',ctx);
 assert.match(html,/<button type="button" aria-pressed="false" class="choice-card/);
 assert.ok(html.includes('data-choice-key='));
});
test('passive skill is described as view rather than activation',()=>{
 const html=table();
 assert.ok(html.includes('查看如影随形'));assert.ok(!html.includes('发动如影随形'));
});

test('choice validation permits declining optional picks and enforces mandatory counts',()=>{
 const ctx=context();
 const check=(kind,count,extra={})=>{ctx.q={kind,...extra};ctx.selected=new Set(Array.from({length:count},(_,i)=>String(i)));return vm.runInContext('conveyorChoiceProgress(q,7)',ctx);};
 assert.equal(check('inspire',0,{maximum:5}).valid,true);
 assert.equal(check('inspire',6,{maximum:5}).valid,false);
 assert.equal(check('split',0).valid,false);
 assert.equal(check('split',7).valid,false);
 assert.equal(check('split',3).valid,true);
 assert.equal(check('discard',1,{count:2}).valid,false);
 assert.equal(check('discard',2,{count:2}).valid,true);
 ctx.q={kind:'clean-main',cards:[{id:'a'}]};
 assert.equal(vm.runInContext('conveyorChoiceProgress(q,7).valid',ctx),true);
 ctx.q={kind:'stars',cards:[{id:'a'},{id:'b'}]};
 assert.equal(vm.runInContext('conveyorChoiceProgress(q,7).valid',ctx),false);
 vm.runInContext('conveyorChosen=["b","a"]',ctx);
 assert.equal(vm.runInContext('conveyorChoiceProgress(q,7).valid',ctx),true);
});
test('blood ending uses mandatory hand trimming without the former draw opt-out',()=>{
 const ctx=context({q:{kind:'discard',seat:0,count:2,title:'重铸·嗜血：弃置两张'},c:{actor:0,actors:[],skill:'blood'}});
 const html=vm.runInContext('conveyorChoice(q,c)',ctx);
 assert.ok(html.includes('hand-choice'));assert.ok(!html.includes('本次不发牌'));assert.ok(!html.includes('name="value"'));
 assert.equal(vm.runInContext('conveyorChoiceProgress(q,7).valid',ctx),false);
 ctx.selected=new Set(['a','b']);assert.equal(vm.runInContext('conveyorChoiceProgress(q,7).valid',ctx),true);
});
test('seven marks uses seven rank and suit selectors instead of raw codes',()=>{
 let html='';const ctx=context({showModal:(_,value)=>html=value});
 ctx.state.features.conveyorSkills.push({id:'seven',name:'七音',text:'储存七枚印记'});
 ctx.state.room={game:{hand:[],conveyor:{skill:'seven',resources:{marks:7}}}};
 vm.runInContext('conveyorUseSkill()',ctx);
 assert.equal((html.match(/name="markRank/g)||[]).length,7);
 assert.equal((html.match(/name="markSuit/g)||[]).length,7);
 assert.ok(!html.includes('placeholder="例如'));
});
test('waiting room post-render does not require a running game',()=>{
 const ctx=context();ctx.state.room={game:null};
 assert.doesNotThrow(()=>vm.runInContext('conveyorAfterRender()',ctx));
});

test('rps offers actions only to eligible players who have not submitted',()=>{
 for(const [reveals,ready,count] of [[[0,1],[],3],[[0,1],[0],0],[[1,2],[],0]]){
  const html=table(false,false,{phase:'rps',reveals,ready});
  assert.equal((html.match(/data-action="rps"/g)||[]).length,count);
  if(ready.includes(0))assert.ok(html.includes('已出拳，等待其他玩家'));
 }
});

test('an eligible player sees the tie result beside the next rps choice',()=>{
 const html=table(false,false,{phase:'rps',reveals:[0,1],ready:[],log:['猜拳平局，请重出。']});
 assert.ok(html.includes('class="rps-feedback"'));
 assert.ok(html.includes('猜拳平局，请重出。'));
 const waiting=table(false,false,{phase:'rps',reveals:[1,2],ready:[],log:['猜拳平局，请重出。']});
 assert.ok(!waiting.includes('class="rps-feedback"'));
});

test('judgment asks for a draw judgment without a hand picker',()=>{
 let html='';const ctx=context({showModal:(_,value)=>html=value});
 ctx.state.features.conveyorSkills.push({id:'judgment',name:'天命',text:'翻牌判定'});
 ctx.state.room={game:{hand:[{id:'card',rank:4,suit:'H'}],conveyor:{skill:'judgment',resources:{}}}};
 vm.runInContext('conveyorUseSkill()',ctx);
 assert.ok(html.includes('翻牌判定'));
 assert.ok(!html.includes('skill-hand-picker'));assert.ok(!html.includes('当前选中'));
});

test('priority countdown occupies its actor area and suspends ordinary turn marker',()=>{
 const html=table(false,false,{priorityClock:{seat:0,actor:1,remaining:4}});
 assert.equal((html.match(/priority-clock/g)||[]).length,1);
 assert.ok(html.includes('优先管牌 4 秒'));
 assert.ok(!html.includes('出牌中...'));
});

test('public player resources include marks and counters for other players',()=>{
 const ctx=context({actor:{skill:'blood',zoneCount:3,resources:{bloodReady:true,blood:4,debt:2,shield:1,ban:2,suits:['S','D']}}});
 const html=vm.runInContext('conveyorResources(actor)',ctx);
 for(const text of ['嗜血 4','奉还 2','免发 1 回合','禁手 2 回合','展示区 3 张','烙印 ♠ ♦'])assert.ok(html.includes(text));
 assert.ok(html.includes('class="red">♦'));
 assert.ok(vm.runInContext("conveyorResources({skill:'money',resources:{money:5}})",ctx).includes('金钱 5'));
 assert.ok(vm.runInContext("conveyorResources({skill:'seven',resources:{marks:3}})",ctx).includes('七音 3/7'));
 assert.ok(vm.runInContext("conveyorResources({skill:'ascend',resources:{boost:2}})",ctx).includes('强化 2 枚 · +2'));
});

test('the fourth use of an urgent card offers only rotation and destruction',async()=>{
 let html='';const ctx=context({state:{room:{game:{hand:[{id:'urgent',rank:18,suit:'U',urgentUses:3},{id:'kept',rank:7,suit:'S'}],conveyor:{actor:0,turnActor:1,actors:[],resources:{}}}}},selected:new Set(['urgent']),urgentSelected:()=>true,wildcardPayload:()=>undefined,showModal:(kind,body)=>{html=body;},$:()=>null});
 vm.runInContext('conveyorUrgentUpdate=()=>{}',ctx);await vm.runInContext('conveyorPlay()',ctx);
 assert.match(html,/value="rotate" selected/);
 for(const effect of ['draw','discard','ban','shield','maximum','silence','judge-boost','judge-color'])assert.match(html,new RegExp('value="'+effect+'"[^>]*disabled'));
 assert.ok(html.includes('本次必须轮换并销毁'));
});

test('suitmark offers only the suits present in the winning play',()=>{
 const ctx=context({q:{kind:'suitmark',seat:0,title:'烙印',suits:['S','D']},c:{},conveyorTargets:()=>''});
 const html=vm.runInContext('conveyorChoice(q,c)',ctx);
 assert.ok(html.includes('name="suit"'));assert.ok(html.includes('value="S"'));assert.ok(html.includes('value="D"'));
 assert.ok(!html.includes('value="H"'));assert.ok(!html.includes('value="C"'));
});

test('a skill selected by another player still opens its description',()=>{
 const ctx=context({r:{host:1,seat:0,players:[{id:1,name:'自己',skill:null},{id:2,name:'别人',skill:'balance'}],skills:[{id:'balance',name:'转换',group:0,deal:7,keep:7,text:'转换'}]}});
 const html=vm.runInContext('conveyorWaiting(r)',ctx);
 assert.ok(html.includes('data-skill="balance"'));
 assert.doesNotMatch(html,/data-skill="balance"[^>]*disabled/);
 assert.ok(html.includes('查看说明'));
});

test('trade offers a judgment during the draw phase',()=>{
 const ctx=context({q:{kind:'deal',seat:0,title:'献祭',maximum:1},c:{actor:0,actors:[],skill:'trade'}});
 const html=vm.runInContext('conveyorChoice(q,c)',ctx);
 assert.match(html,/value="judge">判定/);
});

test('new public marks and optional skill discards are visible and validated',()=>{
 const ctx=context({actor:{skill:'encourage',resources:{inspire:3,prison:1,skillBan:1}}});
 const html=vm.runInContext('conveyorResources(actor)',ctx);
 assert.ok(html.includes('激励 3'));assert.ok(html.includes('禁锢 1'));assert.ok(html.includes('技能封禁'));
 ctx.q={kind:'inspire',maximum:2,title:'激励之力'};
 ctx.selected=new Set(['a','b','c']);assert.equal(vm.runInContext('conveyorChoiceProgress(q,5).valid',ctx),false);
 ctx.selected.clear();assert.equal(vm.runInContext('conveyorChoiceProgress(q,5).valid',ctx),true);
});

test('conveyor displays individual grades and first-place-only victory',()=>{
 const html=table(false,false,{phase:'over',winner:[0],finished:[0,2,1],scores:[2,0,1,0],nextMain:5},{remainingActorHands:{4:[{rank:4,suit:'H'}]}});
 assert.ok(!html.includes('同队'));assert.ok(!html.includes('对手'));
 assert.ok(html.includes('<td>5（不变）</td>'));assert.ok(html.includes('<td>4（不变）</td>'));
 assert.ok(html.includes('conveyor-standings'));
 assert.ok(html.includes('玩家0 获胜'));
 assert.ok(!html.includes('玩家0、玩家2 获胜'));
 assert.ok(html.includes('（不变）'));
 assert.ok(!html.includes('class="board"'));
 assert.ok(!html.includes('class="hand-area"'));
 assert.ok(html.includes('settlement-hands'));
 assert.ok(html.includes('剩余 1 张'));assert.ok(html.includes('settlement-card red'));
 assert.equal((html.match(/class="settlement-hand"/g)||[]).length,1);
});
test('ending single-player practice does not invent a winner or grade reward',()=>{
 const html=table(false,false,{phase:'over',winner:[],finished:[],scores:[0,0,0,0],nextMain:3});
 assert.ok(html.includes('本局结束'));assert.ok(html.includes('等级不变'));
 assert.ok(!html.includes('conveyor-standings'));assert.ok(!html.includes(' 获胜'));
});
