'use strict';
function resetConveyorSelection(){selected.clear();responseKey='';markResponse();}
let conveyorChosen=[], conveyorChoiceKey='', conveyorDouble=null;
const conveyorActiveSkills=new Set(['balance','gift','pressure','ascend','seven','judgment','trade']);
const conveyorGroups={0:'标准',1:'突破',2:'重生',3:'多多益善',4:'智谋'};
const conveyorSkill = id => (state.features?.conveyorSkills||state.room?.skills||[]).find(s=>s.id===id);
function conveyorCreateOptions(){
 const skills=state.features?.conveyorSkills||[];
 return `<fieldset class="conveyor-options"><legend>传送带</legend>${[1,2,3,4].map(n=>`<label class="checkbox"><input name="skillDlc" value="${n}" type="checkbox">DLC · ${conveyorGroups[n]}</label>`).join('')}<details><summary>禁用技能</summary><div class="skill-ban-list">${skills.map(s=>`<label class="checkbox" title="${esc(s.text)}"><input type="checkbox" name="disabledSkills" value="${s.id}">${s.name}<small>${conveyorGroups[s.group]} · ${s.deal} 选 ${s.keep}</small></label>`).join('')}</div></details></fieldset>`;
}
function conveyorFormOptions(form){return {skillDlc:[...form.querySelectorAll('[name="skillDlc"]:checked')].map(e=>Number(e.value)),disabledSkills:[...form.querySelectorAll('[name="disabledSkills"]:checked')].map(e=>e.value)};}
function conveyorWaiting(r){
 const host=r.host===state.user?.id;
 if(r.spectator)return roomHeading(r)+`<section class="watch-waiting"><h2>等待选择技能</h2></section>`;
 const mine=r.players[r.seat]?.skill, missing=r.players.filter(p=>!p.bot&&!p.skill);
 const ready=r.players.length===4&&!missing.length;
 const status=r.players.length<4?'还差 '+(4-r.players.length)+' 位玩家':missing.length?'等待 '+missing.map(p=>esc(p.name)).join('、')+' 选技能':host?'已准备好，可以开始':'已准备好，等待房主开始';
 const groups=Object.entries(conveyorGroups).map(([group,name])=>{
  const skills=r.skills.filter(s=>s.group===Number(group));
  if(!skills.length)return '';
  return `<section class="skill-group"><h3>${name}</h3><div class="skill-grid">${skills.map(s=>{
   const taken=r.players.find(p=>!p.bot&&p.skill===s.id), chosen=mine===s.id;
   return `<button class="skill-card ${chosen?'chosen':''} ${taken&&!chosen?'taken':''}" data-action="cv-skill-info" data-skill="${s.id}" aria-pressed="${chosen}"><strong>${s.name}</strong><small>${s.deal} 选 ${s.keep} · ${conveyorActiveSkills.has(s.id)?'主动技能':'按时机生效'}</small><span>${chosen?'已选择 ✓':taken?esc(taken.name)+' 已选':'查看说明 →'}</span></button>`;
  }).join('')}</div></section>`;
 }).join('');
 const players=Array.from({length:4},(_,i)=>{const p=r.players[i];return `<div class="waiting-seat"><div class="avatar">${p?.bot?'✦':esc(p?.name?.[0]||'＋')}</div><div><strong>${esc(p?.name||'等待加入')}</strong><small>${p?.skill?esc(conveyorSkill(p.skill)?.name):p?.bot?'开局随机选择':'待选择技能'}</small></div>${host&&p?.bot?`<button class="seat-remove" data-action="remove" data-seat="${i}" aria-label="移除${esc(p.name)}">×</button>`:''}</div>`;}).join('');
 return roomHeading(r)+`<div class="conveyor-lobby"><section><div class="conveyor-players">${players}</div>${groups}</section><aside class="side-panel skill-ready"><h3>${mine?'已选 · '+esc(conveyorSkill(mine)?.name):'选择你的技能'}</h3><p>对家组队</p><p class="ready-status" role="status">${status}</p><button class="primary full" data-action="start" ${!host||!ready?'disabled':''}>${host?'开始对局 →':'等待房主开始'}</button>${host?`<button class="secondary full" data-action="bot" ${r.players.length===4?'disabled':''}>邀请规则 AI</button><button class="secondary full" data-action="model-bot" ${r.players.length===4||!state.preferences?.configured?'disabled':''}>邀请模型 AI</button>`:''}</aside></div>`;
}
function conveyorPlayCards(play,g){
 if(!play)return '';
 return `<div class="seat-play-label">${esc(play.kind)}</div><div class="seat-play-cards">${play.cards.map((c,i)=>`<span class="seat-play-card ${['H','D'].includes(c.suit)?'red':''}"><b>${ranks[c.rank]}</b><small>${suits[c.suit]||'○'}${play.ranks[i]!==c.rank?'→'+ranks[play.ranks[i]]:''}${play.suits?.[i]&&play.suits[i]!==c.suit?suits[play.suits[i]]||'○':''}</small></span>`).join('')}</div>`;
}
function conveyorTable(r,g){
 const c=g.conveyor, me=r.seat??0, actor=c.actors.find(a=>a.id===c.actor), own=r.players[me], controlled=!r.spectator&&!own.autoplay, q=c.choice;
 const activeSkill=conveyorActiveSkills.has(c.skill);
 const available=controlled&&g.phase==='play'&&!c.waiting&&!g.finished.includes(me);
 const positions=['bottom','left','top','right'];
 const board=r.players.map((p,s)=>{
  const actors=c.actors.filter(a=>a.owner===s);
  return `<div class="seat ${positions[(s-me+4)%4]} ${(g.phase==='setup'?g.confirmTurn===s:g.turn===s&&g.phase==='play')?'turn':''}"><div class="avatar">${p.bot?'✦':esc(p.name[0])}</div><div><div class="seat-name">${esc(p.name)}${s===me&&!r.spectator?' · 你':''}</div><div class="seat-meta">${actors.map(a=>a.count+(actors.length>1?' 张（'+(actors.indexOf(a)+1)+'）':' 张')).join(' / ')}${p.autoplay?'<span class="autoplay-status">托管中</span>':''}</div><small>${esc(conveyorSkill(p.skill)?.name||'')}${p.skill==='money'?' · 金钱 '+(actors[0]?.resources.money||0):''}</small></div><span class="seat-role">${s%2===me%2?'同队':'对手'}</span><div class="seat-play conveyor-seat-plays">${actors.map(a=>`<div class="actor-play ${a.play?.order===g.playNumber?'latest':'older'}">${['setup','rps','draft'].includes(g.phase)?`<div class="opening-display">${(g.phase==='draft'?a.drafted:a.confirmed)?'<div class="seat-play-label">已确认</div>':(c.waiting?c.actors.find(x=>x.name===c.waiting):c.actors.find(x=>(g.phase==='setup'?x.owner===g.confirmTurn:g.phase!=='rps'||g.reveals.includes(x.owner))&&!(g.phase==='draft'?x.drafted:x.confirmed)))?.id===a.id?'<div class="playing">等待确认...</div>':''}${g.phase!=='draft'&&g.reveals.includes(s)&&actors[0].id===a.id?'<div class="seat-play-label">亮牌</div><div class="seat-play-cards"><span class="seat-play-card"><b>3</b><small>♠</small></span></div>':''}</div>`:g.phase==='play'&&c.turnActor===a.id?'<div class="playing">出牌中...</div>':conveyorPlayCards(a.play,g)}${a.resources.ban?`<small>禁手 ${a.resources.ban}</small>`:''}</div>`).join('')}</div>${r.bubbles?.[s]?`<div class="speech-bubble">${esc(r.bubbles[s])}</div>`:''}</div>`;
 }).join('');
 let center='';
 const pile=`<div class="draw-pile" aria-label="牌堆 ${c.pile} 张"><span class="pile-back">VGC</span><strong>${c.pile} 张</strong></div>`;
 if(g.phase==='draft')center=`<div class="table-prompt">开局选牌</div><p>${c.drafted?'等待其他玩家':'保留 '+c.keep+' 张'}</p>`;
 if(g.phase==='setup')center=`<div class="table-prompt">开局确认</div><div class="phase-actions">${!r.spectator&&g.openingFirst===null&&g.hand.some(x=>x.rank===3&&x.suit==='S')?'<button class="secondary" data-action="reveal">亮黑桃 3</button>':''}${!r.spectator?`<button class="primary" data-action="cv-confirm" ${g.ready.includes(me)?'disabled':''}>${g.ready.includes(me)?'已确认':'确认开始'}</button>`:''}</div>`;
 if(g.phase==='rps')center=`<div class="table-prompt">猜拳定先手</div>${!r.spectator?'<div class="phase-actions">'+[['rock','石头'],['paper','布'],['scissors','剪刀']].map(([v,t])=>`<button class="secondary" data-action="rps" data-value="${v}">${t}</button>`).join('')+'</div>':''}`;
 const result=g.phase==='over'?`<section class="result-banner"><h2>${r.spectator?'本局结束':g.winner.includes(me)?'胜利':'失败'}</h2><p>${g.winner.map(s=>esc(r.players[s].name)).join('、')} 获胜 · 下一局主牌 ${ranks[g.nextMain]}</p><div class="remaining-hands">${c.actors.map(a=>`<section><strong>${esc(a.name)}</strong><div class="settlement-cards">${(c.remainingActorHands?.[a.id]||[]).map(x=>`<span>${ranks[x.rank]}${suits[x.suit]}</span>`).join('')}</div></section>`).join('')}</div></section>`:'';
 const response=g.response?`<div id="response-notice" role="status">可${esc(g.response.moves[0]?.label||'优先管牌')}，已标记手牌。</div>`:'';
 const hand=r.spectator?'':`<section class="hand-area"><div class="hand-top"><strong>${esc(conveyorSkill(c.skill)?.name)} · ${g.hand.length} 张</strong><div class="hand-tools">${g.phase!=='over'?`<button class="primary conveyor-skill-button" data-action="cv-skill-use" ${activeSkill&&(!controlled||g.phase!=='play'||c.waiting||c.turnActor!==c.actor||actor?.resources.ban)?'disabled':''}>${activeSkill?'发动':'查看'}${esc(conveyorSkill(c.skill)?.name||'技能')}</button>`:''}${c.actors.filter(a=>a.owner===me).filter((a,i,list)=>list.length>1).map((a,i)=>`<button class="${a.id===c.actor?'primary':'secondary'}" data-action="cv-focus" data-actor="${a.id}">手牌 ${i===0?'A':'B'}</button>`).join('')}${g.phase!=='over'?`<button class="secondary" data-action="autoplay">${own.autoplay?'取消托管':'托管'}</button>`:''}${own.autoplay?'<span class="autoplay-status">托管中</span>':''}<button class="secondary" data-action="chat-menu">发言</button></div></div><div class="hand ${g.hand.length>23?'dense':''}">${g.hand.map(x=>card(x,controlled&&g.phase!=='over',g)).join('')}</div>${available?`<div class="hand-controls"><div class="controls-left"><button class="text-button" data-action="declare-wild">指定赖子</button>${c.skill==='double'?'<button class="secondary" data-action="cv-double">化双</button>':''}${conveyorDouble?'<span>已指定化双</span>':''}</div><div class="controls-right"><button class="text-button" data-action="deselect">清空 · Esc</button><button class="secondary" data-action="hint">提示</button><button class="secondary" data-action="pass" ${g.turn!==me&&!g.response?'disabled':''}>不出</button><button class="primary" data-action="play">出牌 · Enter →</button></div></div>`:''}${g.phase==='draft'&&!c.drafted?`<div class="draft-controls"><span>${c.waiting?'请先完成当前选择':(c.skill==='twins'?'选择给手牌 A 的 '+c.keep+' 张，其余给 B':'选好 '+c.keep+' 张后确认保留')}</span><button class="primary" data-action="cv-keep" ${!controlled||c.waiting?'disabled':''}>确认保留 ${c.keep} 张</button></div>`:''}<div class="selection-note" id="selection-note">${selected.size?'已选择 '+selected.size+' 张牌':'选择手牌'}${actor?.resources.ban?' · 禁手 '+actor.resources.ban:''}${c.skill==='money'?` · 金钱 ${c.resources.money}`:c.skill==='blood'?` · 血 ${c.resources.blood}`:c.skill==='seven'?` · 印记 ${c.resources.marks||0}`:c.skill==='ascend'?` · 加点 ${1+c.resources.boost}`:''}</div>${c.zone.length?`<details class="conveyor-zone"><summary>分区 · ${c.zone.length} 张未出牌</summary><div>${c.zone.map(x=>`<button class="secondary" data-action="cv-retrieve" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]}</button>`).join('')}</div></details>`:''}${c.boundHands.map(h=>`<details><summary>绑定手牌 · ${esc(h.name)}</summary>${h.cards.map(x=>`${ranks[x.rank]}${suits[x.suit]}`).join(' ')}</details>`).join('')}</section>`;
 return roomHeading(r,true)+result+response+`<div class="table-layout conveyor-table"><section class="board">${board}<div class="table-center">${pile}${center}${c.waiting?`<p>等待 ${esc(c.waiting)} 选择</p>`:''}</div></section><aside class="table-log"><div class="table-log-header">牌桌动态</div><div class="match-meta">弃牌 ${c.discard}<br>主牌 ${ranks[g.main]} · ${g.scores.join(' : ')}</div><div class="log-entries">${g.log.map(t=>`<div class="log-entry">${esc(t)}</div>`).join('')}</div></aside></div>${q&&!own?.autoplay&&q.cards?conveyorChoice(q,c):''}${hand}${q&&!own?.autoplay&&!q.cards?conveyorChoice(q,c):''}`;
}
function conveyorTargets(c, exclude=true){return c.actors.filter(a=>!a.finished&&(!exclude||a.id!==c.actor)).map(a=>`<option value="${a.id}">${esc(a.name)} · ${a.count} 张</option>`).join('');}
function conveyorChoice(q,c){
 const key=JSON.stringify([q.kind,q.seat,q.cards?.map(x=>x.id),q.count,q.left]);
 if(key!==conveyorChoiceKey){conveyorChoiceKey=key;conveyorChosen=[];}
 const cards=q.cards||[];
 const cardChoice=cards.length?`<div class="choice-cards">${cards.map(x=>`<button type="button" aria-pressed="${conveyorChosen.includes(x.id)}" class="choice-card ${conveyorChosen.includes(x.id)?'chosen':''}" data-action="cv-choice-card" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]||'○'}</button>`).join('')}</div><p>${conveyorChosen.map(id=>{const x=cards.find(x=>x.id===id);return ranks[x.rank]+(suits[x.suit]||'○');}).join(q.kind==='stars'?' → ':' · ')}</p>`:'<p>需要选牌时，请在手牌中选择。</p>';
 let extra='';
 if(['pursuit','trade-extra','deal'].includes(q.kind))extra=`<label>获得张数<select name="value">${Array.from({length:(q.maximum||10)+(q.kind==='deal'?0:1)},(_,i)=>q.kind==='deal'?i+1:i).map(n=>`<option value="${n}">${n}</option>`).join('')}</select></label>`;
 if(q.kind==='deal'&&['redirect','request','trade'].includes(c.skill))extra+=`<label>方式<select name="effect"><option value="normal">普通发牌</option><option value="${c.skill==='trade'?'judge':c.skill}">${c.skill==='trade'?'判定':c.skill==='redirect'?'转给别人':'向其他每人索取两张'}</option></select></label>${c.skill==='redirect'?`<label>目标<select name="target">${conveyorTargets(c)}</select></label>`:''}`;
 if(q.kind==='bond')extra=`<label>目标<select name="target"><option value="">不绑定</option>${conveyorTargets(c)}</select></label>`;
 if(['blood-deal','duel-start'].includes(q.kind))extra=`<label>选择<select name="value"><option value="0">${q.kind==='blood-deal'?'本次不发牌':'不发动'}</option><option value="1">${q.kind==='blood-deal'?'获得一张牌':'发起拼点'}</option></select></label>`;
 return `<section class="conveyor-choice" role="region" aria-label="${esc(q.title)}"><h3>${esc(q.title)}</h3><form id="cv-choice-form" data-choice-key="${esc(key)}" class="form">${cards.length||['split','blood','discard','give','duel','stash'].includes(q.kind)?cardChoice:''}${extra}<p class="choice-progress" role="status"></p><p class="form-error"></p><button class="primary" type="submit">确认选择 →</button></form></section>`;
}
function conveyorChoiceProgress(q,handCount){
 const count=q.cards?conveyorChosen.length:selected.size;
 const exact=['maximum','urgent-max','duel'].includes(q.kind)?1:['discard','give'].includes(q.kind)?Math.min(q.count,handCount):q.kind==='stars'?q.cards.length:null;
 const maximum=['retain','buy'].includes(q.kind)?1:q.kind==='blood'?5:q.kind==='split'?handCount-1:null;
 const minimum=['split','scavenge'].includes(q.kind)?1:0;
 const labels={stars:'按点击顺序排列，左侧先发', 'clean-main':'选中的主牌会保留，未选的换牌',retain:'选中的牌会保留',buy:'选中的牌会买入',reflux:'选中的已出牌放回牌堆底',stash:'选中的手牌存入分区',blood:'选中的牌作为血',split:'选中的牌分给手牌 B'};
 const hasCards=!!q.cards||['split','blood','discard','give','duel','stash'].includes(q.kind);
 return {valid:exact!==null?count===exact:count>=minimum&&(maximum===null||count<=maximum),text:hasCards?`${labels[q.kind]||'选择手牌'} · 已选 ${count}${exact!==null?' / '+exact:maximum!==null?' / 最多 '+maximum:minimum?' / 至少 '+minimum:''} 张`:''};
}
function conveyorAfterRender(){
 const r=state.room,g=r.game;
 if(!g)return;
 const q=g.conveyor.choice;
 if(q){const progress=conveyorChoiceProgress(q,g.hand.length),label=$('.choice-progress'),submit=$('#cv-choice-form button[type="submit"]');if(label)label.textContent=progress.text;if(submit)submit.disabled=!progress.valid;}
 if(g.phase==='draft'&&!g.conveyor.drafted){const b=$('[data-action="cv-keep"]');if(b){b.textContent='确认保留 · '+selected.size+' / '+g.conveyor.keep;b.disabled=!!g.conveyor.waiting||!!r.players[r.seat]?.autoplay||selected.size!==g.conveyor.keep;}}
 if(r.audioWaiting||r.players[r.seat]?.autoplay)$$('[data-action^="cv-"]').filter(b=>!['cv-focus','cv-skill-info','cv-skill-card'].includes(b.dataset.action)&&!(b.dataset.action==='cv-skill-use'&&!conveyorActiveSkills.has(g.conveyor.skill))).forEach(b=>b.disabled=true);
 if(r.audioWaiting)$('.conveyor-choice button[type="submit"]')?.setAttribute('disabled','');
}
async function conveyorPlay(){
 const g=state.room.game,c=g.conveyor;
 if(urgentSelected()){
  showModal('cv-urgent',`<h2>急牌</h2><form id="cv-urgent-form" class="form"><label>效果<select name="effect"><option value="draw">目标获得两张</option><option value="discard">弃置附带的零至两张牌</option><option value="ban">目标禁手两回合</option><option value="shield">自己三回合免发牌</option><option value="maximum">目标弃最大牌</option><option value="rotate">轮换手牌</option></select></label><div class="urgent-discard-picker" hidden><p>选择要弃的牌（最多两张，可不选）</p><div class="choice-cards">${g.hand.filter(x=>!selected.has(x.id)&&x.rank!==18).map(x=>`<label class="urgent-discard-card"><input type="checkbox" name="discardIds" value="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]}</label>`).join('')}</div></div><label data-urgent-target>目标<select name="target">${conveyorTargets(c,false)}</select></label><label data-urgent-direction hidden>轮换方向<select name="direction"><option value="counterclockwise">逆时针</option><option value="clockwise">顺时针</option></select></label><p class="form-error"></p><button class="primary">使用急牌</button></form>`);return;
 }
 const args={ids:[...selected],actor:c.actor};const wild=wildcardPayload();if(wild!==undefined)args.wildcard=wild;if(conveyorDouble&&selected.has(conveyorDouble.id))args.double=conveyorDouble;
 if(await gameAction('auto',args)){conveyorDouble=null;wildcard='';wildcardMap={};resetConveyorSelection();renderedKey='';render();}
}
function conveyorUseSkill(){
 const c=state.room.game.conveyor;
 const active={balance:'制衡',gift:'馈赠',pressure:'施压',ascend:'升格',seven:'七印',judgment:'天命',trade:'易牌'};
 if(!active[c.skill]){const s=conveyorSkill(c.skill);showModal('cv-description',`<h2>${esc(s.name)}</h2><p class="skill-description">${esc(s.text)}</p><p>对应时机会提供操作。</p><button class="secondary" data-action="close">关闭</button>`);return;}
 showModal('cv-skill',`<h2>${active[c.skill]}</h2><p class="skill-description">${esc(conveyorSkill(c.skill).text)}</p><p class="skill-picked-count">当前选中 ${selected.size} 张牌。</p><div class="skill-hand-picker" aria-label="技能选牌">${state.room.game.hand.map(x=>`<button type="button" class="choice-card ${selected.has(x.id)?'chosen':''} ${['H','D'].includes(x.suit)?'red':''}" aria-pressed="${selected.has(x.id)}" data-action="cv-skill-card" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]}</button>`).join('')}</div><form class="form" id="cv-skill-form">${['gift','pressure'].includes(c.skill)?`<label>目标<select name="target">${conveyorTargets(c)}</select></label>`:''}${c.skill==='seven'?`<label>操作<select name="effect"><option value="store">储存所选手牌</option><option value="release" ${c.resources.marks!==7?'disabled':''}>使用七印（${c.resources.marks||0} / 7）</option></select></label><fieldset class="seven-picker" hidden><legend>组成七张牌</legend>${Array.from({length:7},(_,i)=>`<label><span>${i+1}</span><select name="markRank${i}" aria-label="第 ${i+1} 张点数">${Array.from({length:15},(_,n)=>n+3).map(n=>`<option value="${n}" ${n===i+3?'selected':''}>${ranks[n]}</option>`).join('')}</select><select name="markSuit${i}" aria-label="第 ${i+1} 张花色">${['S','H','C','D'].map(v=>`<option value="${v}">${suits[v]}</option>`).join('')}</select></label>`).join('')}</fieldset>`:''}<p class="form-error"></p><button class="primary">${c.skill==='balance'?'换 '+selected.size+' 张并结束行动':'确认使用'}</button></form>`);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action^="cv-"]');if(!b||b.disabled)return;
 const action=b.dataset.action,c=state.room?.game?.conveyor;
 try{
 if(action==='cv-skill-info'){const s=conveyorSkill(b.dataset.skill),taken=state.room.players.find(p=>!p.bot&&p.skill===s.id&&p.id!==state.user.id);showModal('cv-skill-info',`<h2>${esc(s.name)}</h2><p>${s.deal} 选 ${s.keep} · ${conveyorGroups[s.group]}</p><p class="skill-description">${esc(s.text)}</p><div class="phase-actions"><button class="secondary" data-action="close">取消</button><button class="primary" data-action="cv-skill-select" data-skill="${s.id}" ${taken?'disabled':''}>${taken?esc(taken.name)+' 已选择':'确认选择'}</button></div>`);}
 if(action==='cv-skill-select'){if(await mutation('skill',{skill:b.dataset.skill}))closeModal();}
 if(action==='cv-keep'){if(await gameAction('keep',{ids:[...selected],actor:c.actor})){resetConveyorSelection();renderedKey='';render();}}
 if(action==='cv-focus'){await gameAction('focus',{actor:Number(b.dataset.actor)});resetConveyorSelection();}
 if(action==='cv-confirm')await gameAction('confirm',{actor:c.actor});
 if(action==='cv-choice-card'){const id=b.dataset.id;conveyorChosen=conveyorChosen.includes(id)?conveyorChosen.filter(i=>i!==id):[...conveyorChosen,id];renderedKey='';render();}
 if(action==='cv-skill-card'){const id=b.dataset.id;selected.has(id)?selected.delete(id):selected.add(id);b.classList.toggle('chosen',selected.has(id));b.setAttribute('aria-pressed',selected.has(id));$('.skill-picked-count').textContent='当前选中 '+selected.size+' 张牌。';if(c.skill==='balance')$('#cv-skill-form button[type=submit], #cv-skill-form button.primary').textContent='换 '+selected.size+' 张并结束行动';selectionUpdate();}
 if(action==='cv-skill-use')conveyorUseSkill();
 if(action==='cv-retrieve')await gameAction('skill',{effect:'retrieve',actor:c.actor,ids:[b.dataset.id]});
 if(action==='cv-double'){
  const hand=state.room.game.hand.filter(x=>selected.has(x.id)&&[13,14,15,state.room.game.main].includes(x.rank));
  if(!hand.length){toast('先选择一张 K、A、2 或主牌。');return;}
  showModal('cv-double',`<h2>化双</h2><form class="form" id="cv-double-form"><label>原牌<select name="id">${hand.map(x=>`<option value="${x.id}">${ranks[x.rank]}${suits[x.suit]}</option>`).join('')}</select></label>${[0,1].map(i=>`<label>第 ${i+1} 张<select name="rank${i}">${[3,4,5].filter(n=>n!==state.room.game.main).map(n=>`<option>${n}</option>`).join('')}</select><select name="suit${i}">${['S','H','C','D'].map(s=>`<option value="${s}">${suits[s]}</option>`).join('')}</select></label>`).join('')}<button class="primary">确认指定</button></form>`);
 }
 }catch(error){toast(error.message);}
});
document.addEventListener('change',e=>{
 const f=e.target.closest('form');if(!f||e.target.name!=='effect')return;
 if(f.id==='cv-urgent-form'){f.querySelector('.urgent-discard-picker').hidden=e.target.value!=='discard';f.querySelector('[data-urgent-target]').hidden=!['draw','ban','maximum'].includes(e.target.value);f.querySelector('[data-urgent-direction]').hidden=e.target.value!=='rotate';}
 if(f.id==='cv-skill-form'&&f.querySelector('.seven-picker'))f.querySelector('.seven-picker').hidden=e.target.value!=='release';
});
document.addEventListener('submit',async e=>{
 const f=e.target;if(!f.id.startsWith('cv-'))return;e.preventDefault();
 const c=state.room.game?.conveyor;
 try{
 if(f.id==='cv-double-form'){conveyorDouble={id:f.elements.id.value,ranks:[0,1].map(i=>Number(f.elements['rank'+i].value)),suits:[0,1].map(i=>f.elements['suit'+i].value)};closeModal();renderedKey='';render();return;}
 const args={actor:c.actor,ids:[...selected]};let action='skill';
 if(f.id==='cv-choice-form'){
  action='choice';args.ids=c.choice.cards?conveyorChosen:[...selected];
  if(f.elements.value)args.value=['duel-start','blood-deal'].includes(c.choice.kind)?f.elements.value.value==='1':Number(f.elements.value.value);
 }
 if(f.id==='cv-urgent-form'){action='urgent';if(f.elements.effect.value==='discard')args.ids=[...new Set([...args.ids,...[...f.querySelectorAll('[name=discardIds]:checked')].map(x=>x.value)])];args.direction=f.elements.direction.value;const wild=wildcardPayload();if(wild!==undefined)args.wildcard=wild;}
 if(f.elements.target&&f.elements.target.value!=='')args.target=Number(f.elements.target.value);
 if(f.elements.effect)args.effect=f.elements.effect.value;
 if(f.elements.markRank0&&args.effect==='release'){args.ranks=Array.from({length:7},(_,i)=>Number(f.elements['markRank'+i].value));args.suits=Array.from({length:7},(_,i)=>f.elements['markSuit'+i].value);}
 if(await gameAction(action,args)){resetConveyorSelection();conveyorChosen=[];if(f.id!=='cv-choice-form')closeModal();renderedKey='';render();}
 }catch(error){const target=f.querySelector('.form-error');if(target)target.textContent=error.message;else toast(error.message);}
});

function conveyorRules(){showModal('cv-rules',`<h2>传送带</h2><p>四人对家，固定 110 张牌，不使用爆牌，沿用 4A4A4 标准牌型和主牌升级，不使用进贡和升变。行动后自动发一张；前两次轮到自己时，出空仍继续发一张；第三次起走完手牌与未出分区才可获胜。只有使用急牌轮换手牌时，才将已出牌放回牌堆底。</p><p>急牌不占普通出牌：可加牌、弃零至两张、禁手、免发牌、弃最大牌或按指定方向轮换手牌。急牌使用后回到牌堆底；未使用的急牌不参与轮换。</p>${(state.room.skills||[]).map(s=>`<details><summary>${esc(s.name)} · ${s.deal} 选 ${s.keep}</summary><p class="skill-description">${esc(s.text)}</p></details>`).join('')}`);}
