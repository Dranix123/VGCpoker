'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('public/conveyor.js','utf8');
function context(extra={}){
 const skills=[{id:'twins',name:'双身',group:3,deal:14,keep:14,text:'两个独立玩家'},{id:'balance',name:'制衡',group:0,deal:7,keep:7,text:'弃置再发牌'}];
 const ctx={state:{user:{id:1},features:{conveyorSkills:skills}},esc:String,ranks:{3:'3',4:'4',5:'5',13:'K',14:'A',18:'急'},suits:{S:'♠',H:'♥',C:'♣',D:'♦'},selected:new Set(),roomHeading:()=>'',card:c=>`<button data-card="${c.id}">${c.rank}</button>`,document:{addEventListener:()=>{}},...extra};
 vm.createContext(ctx);vm.runInContext(source,ctx);return ctx;
}
function table(spectator=false,autoplay=false){
 const players=Array.from({length:4},(_,i)=>({id:i+1,name:'玩家'+i,skill:i===0?'twins':'balance',autoplay:i===0&&autoplay}));
 const actors=Array.from({length:5},(_,i)=>({id:i,owner:i<2?0:i-1,name:'分身'+i,count:2,resources:{},skill:i<2?'twins':'balance'}));
 const c={actor:0,turnActor:1,skill:'twins',actors,pile:50,discard:4,resources:{money:0,blood:0},zone:[],boundHands:[],choice:null};
 const r={seat:spectator?null:0,players,spectator},g={conveyor:c,phase:'play',finished:[],turn:0,hand:[{id:'own',rank:4,suit:'S'}],scores:[0,0],log:[],main:3};
 const ctx=context({r,g});return vm.runInContext('conveyorTable(r,g)',ctx);
}
test('conveyor creation exposes opt-in DLC, default recycling and skill bans',()=>{
 const html=vm.runInContext('conveyorCreateOptions()',context());
 assert.equal((html.match(/name="skillDlc"/g)||[]).length,4);
 assert.ok(/name="recycle"[^>]*checked/.test(html));
 assert.ok(html.includes('name="disabledSkills"'));
});
test('four visible seats render five independent actor play areas',()=>{
 const html=table();
 assert.equal((html.match(/class="seat /g)||[]).length,4);
 assert.equal((html.match(/class="actor-play /g)||[]).length,5);
 assert.ok(html.includes('第 1 手'));assert.ok(html.includes('第 2 手'));
 assert.ok(html.includes('出牌中...'));
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
