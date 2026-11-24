'use strict';
function resetConveyorSelection(){selected.clear();responseKey='';markResponse();}
let conveyorChosen=[], conveyorChoiceKey='', conveyorDouble=null;
const conveyorHandChoices=new Set(['split','discard','give','duel','stash','redemption','inspire']);
const conveyorActiveSkills=new Set(['balance','gift','pressure','ascend','seven','judgment','trade','scavenge','bond']);
const conveyorGroups={0:'标准',1:'突破',2:'重生',3:'多多益善',4:'智谋',5:'终极力量'};
const conveyorSkill = id => (state.features?.conveyorSkills||state.room?.skills||[]).find(s=>s.id===id);
function conveyorCreateOptions(){
 const skills=state.features?.conveyorSkills||[];
 return `<fieldset class="conveyor-options"><legend>传送带</legend>${[1,2,3,4,5].map(n=>`<label class="checkbox"><input name="skillDlc" value="${n}" type="checkbox">DLC · ${conveyorGroups[n]}</label>`).join('')}<details><summary>禁用技能</summary><div class="skill-ban-list">${skills.map(s=>`<label class="checkbox" title="${esc(s.text)}"><input type="checkbox" name="disabledSkills" value="${s.id}">${s.name}<small>${conveyorGroups[s.group]} · ${s.deal} 选 ${s.keep}</small></label>`).join('')}</div></details></fieldset>`;
}
function conveyorFormOptions(form){return {skillDlc:[...form.querySelectorAll('[name="skillDlc"]:checked')].map(e=>Number(e.value)),disabledSkills:[...form.querySelectorAll('[name="disabledSkills"]:checked')].map(e=>e.value)};}
function conveyorBotSkills(r){
 if(r.host!==state.user?.id||!r.players.some(p=>p.bot))return '';
 return `<fieldset class="form conveyor-bot-skills"><legend>指定 AI 技能</legend>${r.players.map((p,i)=>p.bot?`<label>${esc(p.name)}<select data-cv-bot-skill="${i}"><option value="">随机选择</option>${r.skills.map(s=>`<option value="${esc(s.id)}" ${p.botSkill===s.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>`:'').join('')}</fieldset>`;
}
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
   const chosen=mine===s.id;
   return `<button class="skill-card ${chosen?'chosen':''}" data-action="cv-skill-info" data-skill="${s.id}" aria-pressed="${chosen}"><strong>${s.name}</strong><small>${s.deal} 选 ${s.keep} · ${conveyorActiveSkills.has(s.id)?'主动技能':'按时机生效'}</small><span>${chosen?'已选择 ✓':'查看说明 →'}</span></button>`;
  }).join('')}</div></section>`;
 }).join('');
 const players=Array.from({length:4},(_,i)=>{const p=r.players[i];return `<div class="waiting-seat"><div class="avatar">${p?.bot?'✦':esc(p?.name?.[0]||'＋')}</div><div><strong>${esc(p?.name||'等待加入')}</strong><small>${p?.skill?esc(conveyorSkill(p.skill)?.name):p?.bot?'开局随机选择':'待选择技能'}</small></div>${host&&p?.bot?`<button class="seat-remove" data-action="remove" data-seat="${i}" aria-label="移除${esc(p.name)}">×</button>`:''}</div>`;}).join('');
 return roomHeading(r)+`<div class="conveyor-lobby"><section><div class="conveyor-players">${players}</div>${groups}</section><aside class="side-panel skill-ready"><h3>${mine?'已选 · '+esc(conveyorSkill(mine)?.name):'选择你的技能'}</h3><p>各自为战 · 第一名升2级，第二名升1级</p>${conveyorBotSkills(r)}<p class="ready-status" role="status">${status}</p><button class="primary full" data-action="start" ${!host||!ready?'disabled':''}>${host?'开始对局 →':'等待房主开始'}</button>${host?`<button class="secondary full" data-action="bot" ${r.players.length===4?'disabled':''}>邀请规则 AI</button><button class="secondary full" data-action="model-bot" ${r.players.length===4||!state.preferences?.configured?'disabled':''}>邀请模型 AI</button>`:''}</aside></div>`;
}
function conveyorResources(actor,label=''){
 const r=actor.resources,stats=[];
 if(actor.skill==='money')stats.push('金钱 '+r.money);
 if(actor.skill==='blood')stats.push('嗜血 '+r.blood);
 if(actor.skill==='seven')stats.push('七音 '+(r.marks||0)+'/7');
 if(actor.skill==='ascend')stats.push('强化 '+r.boost+' 枚 · +'+(1+r.boost));
 if(r.prison)stats.push('禁锢 '+r.prison);
 if(r.inspire)stats.push('激励 '+r.inspire);
 if(r.skillBan)stats.push('技能封禁 '+r.skillBan+' 回合');
 if(r.judgeBoost)stats.push('判定强化 +'+(r.judgeBoost*5));
 if(r.judgeColor)stats.push('判定同色 '+r.judgeColor+' 枚');
 if(r.debt)stats.push('奉还 '+r.debt);
 if(r.shield)stats.push('免发 '+r.shield+' 回合');
 if(r.ban)stats.push('禁手 '+r.ban+' 回合');
 if(actor.zoneCount)stats.push('展示区 '+actor.zoneCount+' 张');
 if(actor.boundTo?.length)stats.push('绑定 '+actor.boundTo.join('、'));
 const marks=r.suits||[];
 if(!stats.length&&!marks.length)return '';
 return `<div class="conveyor-resources">${label?`<strong>${label}</strong>`:''}${stats.map(text=>`<span title="${esc(text)}">${esc(text)}</span>`).join('')}${marks.length?`<span class="conveyor-marks" aria-label="烙印 ${marks.map(s=>suits[s]).join(' ')}">烙印 ${marks.map(s=>`<b class="${['H','D'].includes(s)?'red':''}">${suits[s]}</b>`).join('')}</span>`:''}</div>`;
}
function conveyorTable(r,g){
 const c=g.conveyor, me=r.seat??0, actor=c.actors.find(a=>a.id===c.actor), own=r.players[me], controlled=!r.spectator&&!own.autoplay&&!g.finished.includes(me), q=c.choice;
 const activeSkill=conveyorActiveSkills.has(c.skill)&&!c.resources?.skillBan;
 const available=controlled&&g.phase==='play'&&!c.waiting&&!g.finished.includes(me);
 const positions=['bottom','left','top','right'];
 const waitingActor=c.waitingActor??(c.waiting?c.actors.find(a=>a.name===c.waiting)?.id:null);
 const actingSeat=waitingActor!=null?c.actors.find(a=>a.id===waitingActor)?.owner:g.phase==='setup'?g.confirmTurn:g.phase==='play'?(g.priorityClock?.seat??g.turn):null;
 const board=r.players.map((p,s)=>{
  const actors=c.actors.filter(a=>a.owner===s),place=g.finished.indexOf(s),skill=conveyorSkill(actors[0]?.skill??p.skill);
  return `<div class="seat ${positions[(s-me+4)%4]} ${actingSeat===s?'turn':''}"><div class="avatar">${p.bot?'✦':esc(p.name[0])}</div><div><div class="seat-name">${esc(p.name)}${s===me&&!r.spectator?' · 你':''}</div><div class="seat-meta">${place>=0?'第 '+(place+1)+' 名 · 已走完':actors.map(a=>a.count+(actors.length>1?' 张（'+(actors.indexOf(a)===0?'A':'B')+'）':' 张')).join(' / ')}${p.autoplay?'<span class="autoplay-status">托管中</span>':''}</div>${skill?`<button type="button" class="text-button seat-skill" data-action="cv-skill-info" data-skill="${esc(skill.id)}" aria-label="查看 ${esc(p.name)} 的技能：${esc(skill.name)}">${esc(skill.name)}</button>`:''}${actors.map((a,i)=>conveyorResources(a,actors.length>1?i===0?'A':'B':'')).join('')}</div><span class="seat-role">等级 ${ranks[(g.scores[s]||0)+3]}</span><div class="seat-play conveyor-seat-plays">${actors.map(a=>`<div class="actor-play ${a.play?.order===g.playNumber?'latest':'older'}">${waitingActor===a.id?'<div class="playing">选择中...</div>':['setup','rps','draft'].includes(g.phase)?`<div class="opening-display">${(g.phase==='draft'?a.drafted:a.confirmed)?`<div class="seat-play-label">${g.phase==='draft'?'已选牌':g.phase==='rps'?'已出拳':'已确认'}</div>`:(c.waiting?c.actors.find(x=>x.name===c.waiting):c.actors.find(x=>(g.phase==='setup'?x.owner===g.confirmTurn&&(c.confirmationActors?.includes(x.id)??true):g.phase!=='rps'||g.reveals.includes(x.owner))&&!(g.phase==='draft'?x.drafted:x.confirmed)))?.id===a.id?`<div class="playing">${g.phase==='draft'?'选牌中...':g.phase==='rps'?'等待出拳...':'等待确认...'}</div>`:''}${g.phase!=='draft'&&g.reveals.includes(s)&&actors[0].id===a.id?'<div class="seat-play-label">亮牌</div><div class="seat-play-cards"><span class="seat-play-card"><b>3</b><small>♠</small></span></div>':''}</div>`:g.phase==='play'&&g.priorityClock?.actor===a.id?`<div class="playing priority-clock" role="status">${g.priorityClock.paused?'优先管牌 · 计时暂停':'优先管牌 '+g.priorityClock.remaining+' 秒'}</div>`:g.phase==='play'&&!g.priorityClock&&c.turnActor===a.id&&!c.waiting?'<div class="playing">出牌中...</div>':a.play?seatPlayCards(a.play,g):''}</div>`).join('')}</div>${r.bubbles?.[s]?`<div class="speech-bubble">${esc(r.bubbles[s])}</div>`:''}</div>`;
 }).join('');
 let center='',openingActions='';
 const pile=`<div class="draw-pile" aria-label="牌堆 ${c.pile} 张"><span class="pile-back">VGC</span><strong>${c.pile} 张</strong></div>`;
 if(g.phase==='draft')center=`<div class="table-prompt">开局选牌</div><p>${c.drafted?'等待其他玩家':c.skill==='twins'?'给 A '+c.keep+' 张，其余给 B':'保留 '+c.keep+' 张'}</p>`;
 if(g.phase==='setup'){center='<div class="table-prompt">开局亮牌</div>';if(g.confirmationSeats?.includes(me)??true)openingActions=`<div class="phase-actions conveyor-opening-actions">${!r.spectator&&c.skill!=='scavenge'&&g.openingFirst===null&&g.hand.some(x=>x.rank===3&&x.suit==='S')?'<button class="secondary" data-action="reveal">亮黑桃 3</button>':''}${!r.spectator?`<button class="primary" data-action="cv-confirm" ${g.ready.includes(me)?'disabled':''}>${g.ready.includes(me)?'已确认':'确认开始'}</button>`:''}</div>`}
 if(g.phase==='rps'){center='<div class="table-prompt">猜拳定先手</div>';openingActions=!r.spectator&&g.reveals.includes(me)&&!g.ready.includes(me)?'<div class="phase-actions conveyor-opening-actions">'+[['rock','石头'],['paper','布'],['scissors','剪刀']].map(([v,t])=>`<button class="secondary" data-action="rps" data-value="${v}">${t}</button>`).join('')+'</div>':`<p class="opening-wait">${g.ready.includes(me)?'已出拳，等待其他玩家':'亮牌玩家正在猜拳'}</p>`;const report=[...g.log].reverse().find(text=>text.startsWith('猜拳平局')||text.startsWith('猜拳胜者'));if(report&&g.reveals.includes(me)&&!g.ready.includes(me))openingActions=`<p class="rps-feedback" role="status">${esc(report)}</p>`+openingActions;}
 const order=[...g.finished,...r.players.map((_,seat)=>seat).filter(seat=>!g.finished.includes(seat))];
 const standings=g.phase==='over'&&g.winner.length?`<table class="conveyor-standings"><thead><tr><th>名次</th><th>玩家</th><th>等级</th></tr></thead><tbody>${order.map((seat,index)=>`<tr><td>${index+1}</td><td>${esc(r.players[seat].name)}</td><td>${ranks[g.scores[seat]+3]}${c.gradeChanges?.[seat]?'（+'+c.gradeChanges[seat]+'）':'（不变）'}</td></tr>`).join('')}</tbody></table>`:'';
 const result=g.phase==='over'?`<section class="result-banner"><h2>${r.spectator||!g.winner.length?'本局结束':g.winner.includes(me)?'胜利':'失败'}</h2><p>${g.winner.length?g.winner.map(s=>esc(r.players[s].name)).join('、')+' 获胜 · 下一局主牌 '+ranks[g.nextMain]:'等级不变'}</p>${standings}<div class="settlement-hands">${c.actors.filter(a=>c.remainingActorHands?.[a.id]?.length).map(a=>{const cards=c.remainingActorHands[a.id];return `<section class="settlement-hand"><h3>${esc(a.name)} <small>剩余 ${cards.length} 张</small></h3><div class="settlement-cards">${cards.length?cards.map(x=>`<span class="settlement-card ${['H','D'].includes(x.suit)||x.rank===17?'red':''}">${ranks[x.rank]}${suits[x.suit]}</span>`).join(''):'<span class="muted">已出完</span>'}</div></section>`;}).join('')}</div></section>`:'';
 if(g.phase==='over')return roomHeading(r,true)+result+conveyorBotSkills(r);
 const focus=c.actors.filter(a=>a.owner===me);
 const cardOptions=g.hand.some(x=>x.rank===14&&(x.suit==='S'||c.skill==='wild'))?'<button class="text-button" data-action="declare-wild" hidden>指定赖子</button>':'';
 const options=cardOptions+(c.skill==='double'?'<button class="text-button" data-action="cv-double" hidden>拆解</button>':'');
 const skillButton=`<button class="${activeSkill?'secondary':'text-button'} conveyor-skill-button" data-action="cv-skill-use" ${activeSkill&&(!controlled||g.phase!=='play'||c.skill!=='pressure'&&(c.waiting||c.turnActor!==c.actor)||actor?.resources.ban)?'disabled':''}>${activeSkill&&c.skill==='scavenge'?'取牌并跳过':(activeSkill?'发动':'查看')+esc(conveyorSkill(c.skill)?.name||'技能')}</button>`;
 const focusButtons=focus.length>1&&g.phase!=='draft'?`<div class="hand-identities" aria-label="切换手牌">${focus.map((a,i)=>`<button class="${a.id===c.actor?'primary':'secondary'}" data-action="cv-focus" data-actor="${a.id}" aria-pressed="${a.id===c.actor}">手牌 ${i===0?'A':'B'} · ${a.count}${g.phase==='play'&&a.id===c.turnActor?' · 出牌':''}</button>`).join('')}</div>`:'';
 const draft=g.phase==='draft'&&!c.drafted?`<div class="draft-controls"><span>${c.waiting?'请先完成当前选择':c.skill==='twins'?'选择给手牌 A 的 '+c.keep+' 张，其余给 B':'请选择 '+c.keep+' 张保留'}</span><button class="primary" data-action="cv-keep" ${!controlled||c.waiting?'disabled':''}>确认保留 ${c.keep} 张</button></div>`:'';
 const zones=`${c.zone.length?`<details class="conveyor-zone" data-table-panel="zone"><summary>展示区 · ${c.zone.length} 张未出牌</summary><div>${c.zone.map(x=>`<button class="secondary" data-action="cv-retrieve" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]}</button>`).join('')}</div></details>`:''}${c.boundHands.map(h=>`<details data-table-panel="bound-${esc(h.seat??h.name)}"><summary>绑定手牌 · ${esc(h.name)}</summary>${h.cards.map(x=>`${ranks[x.rank]}${suits[x.suit]}${x.effective!==undefined&&x.effective!==x.rank?'→'+(x.effective===g.main?'主':'')+ranks[x.effective]:''}`).join(' ')}${h.zone?.length?`<p>未出展示区：${h.zone.map(x=>`${ranks[x.rank]}${suits[x.suit]}`).join(' ')}</p>`:''}</details>`).join('')}`;
 const hand=r.spectator?'':`<section class="hand-area"><div class="hand-top"><strong>${g.finished.includes(me)?'已走完':own.autoplay?'托管中':`手牌 <span class="muted">/ ${g.hand.length} 张</span>`}</strong><div class="hand-tools">${skillButton}${handTools(r)}</div></div>${focusButtons}${openingActions}<div class="hand ${g.hand.length>23?'dense':''}">${g.hand.map(x=>card(x,controlled&&g.phase!=='over',g)).join('')}</div>${available?actionDock(options):''}${draft}${zones}</section>`;
 return roomHeading(r,true)+`<div class="table-layout conveyor-table"><section class="board" data-table="${esc(tableKey(r))}">${board}<div class="table-center">${pile}${center}${c.waiting?`<p>等待 ${esc(c.waiting)} 选择</p>`:''}</div></section>${tableHistory(g,`弃牌 ${c.discard}${c.destroyed?' · 已销毁急牌 '+c.destroyed:''}`)}</div>${q&&!own?.autoplay&&!conveyorHandChoices.has(q.kind)?conveyorChoice(q,c):''}${hand}${q&&!own?.autoplay&&conveyorHandChoices.has(q.kind)?conveyorChoice(q,c):''}${publicHandsPanel(r,g)}`;
}
function conveyorTargets(c, exclude=true){return c.actors.filter(a=>!a.finished&&(!exclude||a.id!==c.actor)).map(a=>`<option value="${a.id}">${esc(a.name)} · ${a.count} 张</option>`).join('');}
function conveyorChoice(q,c){
 const key=JSON.stringify([q.kind,q.seat,q.cards?.map(x=>x.id),q.count,q.left]);
 if(key!==conveyorChoiceKey){conveyorChoiceKey=key;conveyorChosen=[];}
 const cards=q.cards||[];
 const cardChoice=cards.length?`<div class="choice-cards">${cards.map(x=>`<button type="button" aria-pressed="${conveyorChosen.includes(x.id)}" class="choice-card ${conveyorChosen.includes(x.id)?'chosen':''} ${['H','D'].includes(x.suit)||x.rank===17?'red':''}" data-action="cv-choice-card" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]||'○'}${q.kind==='stars'&&conveyorChosen.includes(x.id)?`<small class="choice-order" aria-hidden="true">${conveyorChosen.indexOf(x.id)+1}</small>`:''}</button>`).join('')}</div><p>${conveyorChosen.map(id=>{const x=cards.find(x=>x.id===id);return ranks[x.rank]+(suits[x.suit]||'○');}).join(q.kind==='stars'?' → ':' · ')}</p>`:'<p>需要选牌时，请在手牌中选择。</p>';
 let extra='';
 if(['pursuit','deal'].includes(q.kind))extra=`<label>获得张数<select name="value">${Array.from({length:(q.maximum||10)+(q.kind==='pursuit'?1:0)},(_,i)=>q.kind==='pursuit'?i:i+1).map(n=>`<option value="${n}">${n}</option>`).join('')}</select></label>`;
 if(q.kind==='deal'&&['redirect','request','trade'].includes(c.skill))extra+=`<label>方式<select name="effect"><option value="normal">普通发牌</option><option value="${c.skill==='trade'?'judge':c.skill}">${c.skill==='trade'?'判定':c.skill==='redirect'?'转给别人':'向其他每人窃取两张'}</option></select></label>${c.skill==='redirect'?`<label>目标<select name="target">${conveyorTargets(c)}</select></label>`:''}`;
 if(q.kind==='bond')extra=`<label>目标<select name="target">${q.required?'':'<option value="">保持现状</option>'}${conveyorTargets(c)}</select></label>`;
 if(q.kind==='suitmark')extra=`<label>烙印花色<select name="suit">${q.suits.map(s=>`<option value="${s}">${suits[s]}</option>`).join('')}</select></label>`;
 if(q.kind==='duel-start')extra='<label>选择<select name="value"><option value="0">不发动</option><option value="1">发起死斗</option></select></label>';
 return `<section class="conveyor-choice ${conveyorHandChoices.has(q.kind)&&!q.cards?'hand-choice':''}" role="region" aria-label="${esc(q.title)}"><h3>${esc(q.title)}</h3><form id="cv-choice-form" data-choice-key="${esc(key)}" class="form">${cards.length||conveyorHandChoices.has(q.kind)?cardChoice:''}${extra}<p class="form-error"></p><div class="choice-actions"><p class="choice-progress" role="status"></p>${q.kind==='stars'?'<button type="button" class="secondary" data-action="cv-choice-original">保持原顺序</button>':''}<button class="primary" type="submit">确认选择 →</button></div></form></section>`;
}
function conveyorChoiceProgress(q,handCount){
 const count=q.cards?conveyorChosen.length:selected.size;
 const exact=['maximum','urgent-max','duel'].includes(q.kind)?1:['discard','give'].includes(q.kind)?Math.min(q.count,handCount):q.kind==='stars'?q.cards.length:null;
 const maximum=['retain','buy'].includes(q.kind)?1:q.kind==='split'?handCount-1:['redemption','inspire','scavenge'].includes(q.kind)?q.maximum??null:null;
 const minimum=['split','scavenge'].includes(q.kind)?1:0;
 const labels={redemption:q.title,inspire:q.title,discard:q.title,give:q.title,duel:q.title,stars:'按点击顺序排列，左侧先发',retain:'选中的牌会保留',buy:'选中的牌会买入',reflux:'选中的已出牌放回牌堆底',stash:'选中的手牌存入展示区',split:'选中的牌分给手牌 B'};
 const hasCards=!!q.cards||conveyorHandChoices.has(q.kind);
 return {valid:exact!==null?count===exact:count>=minimum&&(maximum===null||count<=maximum),text:hasCards?`${labels[q.kind]||'选择手牌'} · 已选 ${count}${exact!==null?' / '+exact:maximum!==null?' / 最多 '+maximum:minimum?' / 至少 '+minimum:''} 张`:''};
}
function conveyorAfterRender(){
 const r=state.room,g=r.game;
 if(!g)return;
 const q=g.conveyor.choice;
 if(q){const progress=conveyorChoiceProgress(q,g.hand.length),label=$('.choice-progress'),submit=$('#cv-choice-form button[type="submit"]');if(label)label.textContent=progress.text;if(submit)submit.disabled=!progress.valid;}
 if(g.phase==='draft'&&!g.conveyor.drafted){const b=$('[data-action="cv-keep"]');if(b){b.textContent=(g.conveyor.skill==='twins'?'确认分牌':'确认保留')+' · '+selected.size+' / '+g.conveyor.keep;b.disabled=!!g.conveyor.waiting||!!r.players[r.seat]?.autoplay||selected.size!==g.conveyor.keep;}}
 if(r.audioWaiting||r.players[r.seat]?.autoplay)$$('[data-action^="cv-"]').filter(b=>!['cv-focus','cv-skill-info','cv-skill-card'].includes(b.dataset.action)&&!(b.dataset.action==='cv-skill-use'&&!conveyorActiveSkills.has(g.conveyor.skill))).forEach(b=>b.disabled=true);
 if(r.audioWaiting)$('.conveyor-choice button[type="submit"]')?.setAttribute('disabled','');
}
async function conveyorPlay(){
 const g=state.room.game,c=g.conveyor;
 if(urgentSelected()){
  if(c.waiting||c.resources?.ban){toast(c.waiting?'请先完成当前选择。':'禁手期间不能使用急牌。');return;}
  const wild=wildcardPayload(),urgentIds=g.hand.filter(x=>selected.has(x.id)&&((x.effective??x.rank)===18||x.rank===14&&(x.suit==='S'||c.skill==='wild')&&(typeof wild==='object'?wildRank(wild[x.id])===18:wild===18))).map(x=>x.id);
  if(urgentIds.length!==1){toast('每次选择一张急牌。');return;}
  const uses=g.hand.find(x=>x.id===urgentIds[0]).urgentUses||0,forced=uses>=3;
  showModal('cv-urgent',`<h2>急牌</h2><p>此牌已使用 ${uses} 次${forced?'，本次必须轮换并销毁':'；不废弃使用最多三次'}。</p><form id="cv-urgent-form" class="form">${urgentIds.map(id=>`<input type="hidden" name="urgentIds" value="${esc(id)}">`).join('')}<label>效果<select name="effect">${[['draw','目标获得两张'],['discard','弃置零至两张，至少留一张'],['ban','目标禁手两回合'],['shield','自己三回合免发牌'],['maximum','目标弃最大牌（剩一张无效）'],['silence','封禁目标技能三回合'],['judge-boost','判定点数强化'],['judge-color','判定花色强化'],['rotate','轮换手牌并销毁急牌']].map(([effect,text])=>`<option value="${effect}" ${effect==='rotate'&&forced?'selected':''} ${forced&&effect!=='rotate'||effect==='discard'&&g.hand.length===1?'disabled':''}>${text}</option>`).join('')}</select></label><div class="urgent-discard-picker" hidden><p class="urgent-discard-count">选择要弃的牌（最多两张，可不选）</p><div class="choice-cards">${g.hand.filter(x=>!urgentIds.includes(x.id)&&(x.effective??x.rank)!==18).map(x=>`<label class="urgent-discard-card ${['H','D'].includes(x.suit)?'red':''}"><span>${ranks[x.rank]}${suits[x.suit]}</span><input type="checkbox" name="discardIds" value="${esc(x.id)}" ${selected.has(x.id)?'checked':''}></label>`).join('')}</div></div><label data-urgent-target>目标<select name="target">${conveyorTargets(c,false)}</select></label><label data-urgent-direction hidden>轮换方向<select name="direction"><option value="counterclockwise">逆时针</option><option value="clockwise">顺时针</option></select></label><p class="form-error"></p><button class="primary">使用急牌</button></form>`);conveyorUrgentUpdate($('#cv-urgent-form'));return;
 }
 if(await gameAction('auto',selectedPlay())){conveyorDouble=null;wildcardMap={};resetConveyorSelection();renderedKey='';render();}
}
async function conveyorUseSkill(){
 const c=state.room.game.conveyor;
 if(c.resources?.skillBan){const s=conveyorSkill(c.skill);showModal('cv-description',`<h2>${esc(s.name)}</h2><p>技能封禁 · 剩余 ${c.resources.skillBan} 回合</p><p class="skill-description">${esc(s.text)}</p><button class="secondary" data-action="close">关闭</button>`);return;}
 if(['scavenge','bond'].includes(c.skill)){await gameAction('skill',{actor:c.actor});resetConveyorSelection();return;}
 const active={balance:'转换',gift:'恩赐',pressure:'施压',ascend:'重铸·至高强化',seven:'重铸·七音',judgment:'投骰',trade:'献祭',bond:'灵魂绑定'};
 if(!active[c.skill]){const s=conveyorSkill(c.skill);showModal('cv-description',`<h2>${esc(s.name)}</h2><p class="skill-description">${esc(s.text)}</p><p>对应时机会提供操作。</p><button class="secondary" data-action="close">关闭</button>`);return;}
 showModal('cv-skill',`<h2>${active[c.skill]}</h2><p class="skill-description">${esc(conveyorSkill(c.skill).text)}</p>${c.skill==='judgment'?'':`<p class="skill-picked-count">当前选中 ${selected.size} 张牌。</p><div class="skill-hand-picker" aria-label="技能选牌">${state.room.game.hand.map(x=>`<button type="button" class="choice-card ${selected.has(x.id)?'chosen':''} ${['H','D'].includes(x.suit)?'red':''}" aria-pressed="${selected.has(x.id)}" data-action="cv-skill-card" data-id="${esc(x.id)}">${ranks[x.rank]}${suits[x.suit]}</button>`).join('')}</div>`}<form class="form" id="cv-skill-form">${['gift','pressure'].includes(c.skill)?`<label>目标<select name="target">${conveyorTargets(c)}</select></label>`:''}${c.skill==='seven'?`<label>操作<select name="effect"><option value="store">储存所选手牌</option><option value="release" ${c.resources.marks!==7?'disabled':''}>使用重铸·七音（${c.resources.marks||0} / 7）</option></select></label><fieldset class="seven-picker" hidden><legend>组成七连顺子</legend>${Array.from({length:7},(_,i)=>`<label><span>${i+1}</span><select name="markRank${i}" aria-label="第 ${i+1} 张点数">${Array.from({length:12},(_,n)=>n+3).map(n=>`<option value="${n}" ${n===i+3?'selected':''}>${ranks[n]}</option>`).join('')}</select><select name="markSuit${i}" aria-label="第 ${i+1} 张花色">${['S','H','C','D'].map(v=>`<option value="${v}">${suits[v]}</option>`).join('')}</select></label>`).join('')}</fieldset>`:''}<p class="form-error"></p><button class="primary">${c.skill==='balance'?'换 '+selected.size+' 张并结束行动':c.skill==='judgment'?'翻牌判定':'确认使用'}</button></form>`);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-action^="cv-"]');if(!b||b.disabled)return;
 const action=b.dataset.action,c=state.room?.game?.conveyor;
 try{
 if(action==='cv-skill-info'){const s=conveyorSkill(b.dataset.skill);if(!s)return;showModal('cv-skill-info',`<h2>${esc(s.name)}</h2><p>${s.deal} 选 ${s.keep} · ${conveyorGroups[s.group]}</p><p class="skill-description">${esc(s.text)}</p><div class="phase-actions"><button class="secondary" data-action="close">${c?'关闭':'取消'}</button>${c?'':`<button class="primary" data-action="cv-skill-select" data-skill="${s.id}">确认选择</button>`}</div>`);}
 if(action==='cv-skill-select'){if(await mutation('skill',{skill:b.dataset.skill}))closeModal();}
 if(action==='cv-keep'){if(await gameAction('keep',{ids:[...selected],actor:c.actor})){resetConveyorSelection();renderedKey='';render();}}
 if(action==='cv-focus'){await gameAction('focus',{actor:Number(b.dataset.actor)});resetConveyorSelection();}
 if(action==='cv-confirm')await gameAction('confirm',{actor:c.actor});
 if(action==='cv-choice-original'){conveyorChosen=c.choice.cards.map(x=>x.id);$('#cv-choice-form').requestSubmit();}
 if(action==='cv-choice-card'){const id=b.dataset.id;conveyorChosen=conveyorChosen.includes(id)?conveyorChosen.filter(i=>i!==id):[...conveyorChosen,id];renderedKey='';render();}
 if(action==='cv-skill-card'){const id=b.dataset.id;selected.has(id)?selected.delete(id):selected.add(id);b.classList.toggle('chosen',selected.has(id));b.setAttribute('aria-pressed',selected.has(id));$('.skill-picked-count').textContent='当前选中 '+selected.size+' 张牌。';if(c.skill==='balance')$('#cv-skill-form button[type=submit], #cv-skill-form button.primary').textContent='换 '+selected.size+' 张并结束行动';selectionUpdate();}
 if(action==='cv-skill-use')conveyorUseSkill();
 if(action==='cv-retrieve')await gameAction('skill',{effect:'retrieve',actor:c.actor,ids:[b.dataset.id]});
 if(action==='cv-double'){
  const hand=state.room.game.hand.filter(x=>selected.has(x.id)&&[13,14,15,state.room.game.main].includes(x.rank));
  if(!hand.length){toast('先选择一张 K、A、2 或主牌。');return;}
  showModal('cv-double',`<h2>拆解</h2><form class="form" id="cv-double-form"><label>原牌<select name="id">${hand.map(x=>`<option value="${x.id}">${ranks[x.rank]}${suits[x.suit]}</option>`).join('')}</select></label>${[0,1].map(i=>`<label>第 ${i+1} 张<select name="rank${i}">${[3,4,5].filter(n=>n!==state.room.game.main).map(n=>`<option>${n}</option>`).join('')}</select><select name="suit${i}">${['S','H','C','D'].map(s=>`<option value="${s}">${suits[s]}</option>`).join('')}</select></label>`).join('')}<button class="primary">确认指定</button></form>`);
 }
 }catch(error){toast(error.message);}
});
function conveyorUrgentUpdate(form){
 const effect=form.elements.effect.value;
 form.querySelector('.urgent-discard-picker').hidden=effect!=='discard';
 form.querySelector('[data-urgent-target]').hidden=!['draw','ban','maximum','silence'].includes(effect);
 form.querySelector('[data-urgent-direction]').hidden=effect!=='rotate';
 const boxes=[...form.querySelectorAll('[name=discardIds]')],count=boxes.filter(x=>x.checked).length,discard=form.elements.effect.value==='discard',limit=Math.min(2,Math.max(0,state.room.game.hand.length-2));
 form.querySelector('.urgent-discard-count').textContent='已选 '+count+' / '+limit+' 张，至少留一张手牌';
 boxes.forEach(x=>{x.disabled=count>=limit&&!x.checked;x.closest('label').classList.toggle('chosen',x.checked);});
 form.querySelector('button.primary').disabled=discard&&count>limit;
}
document.addEventListener('change',async e=>{
 const botSeat=e.target.dataset.cvBotSkill;
 if(botSeat!==undefined){
  if(!await mutation('skill',{botSeat:Number(botSeat),skill:e.target.value||null}))e.target.value=state.room?.players[botSeat]?.botSkill||'';
  return;
 }
 const f=e.target.closest('form');if(!f)return;if(f.id==='cv-urgent-form')conveyorUrgentUpdate(f);if(e.target.name!=='effect')return;
 if(f.id==='cv-skill-form'&&f.querySelector('.seven-picker')){const release=e.target.value==='release';f.querySelector('.seven-picker').hidden=!release;$('#modal .skill-hand-picker').hidden=release;$('#modal .skill-picked-count').hidden=release;}
});
document.addEventListener('submit',async e=>{
 const f=e.target;if(!f.id.startsWith('cv-'))return;e.preventDefault();
 const c=state.room.game?.conveyor;
 try{
 if(f.id==='cv-double-form'){conveyorDouble={id:f.elements.id.value,ranks:[0,1].map(i=>Number(f.elements['rank'+i].value)),suits:[0,1].map(i=>f.elements['suit'+i].value)};closeModal();renderedKey='';render();return;}
 const error=f.querySelector('.form-error');if(error)error.textContent='';
 const args={actor:c.actor,ids:c.skill==='judgment'&&f.id==='cv-skill-form'?[]:[...selected]};let action='skill';
 if(f.id==='cv-choice-form'){
  action='choice';args.ids=c.choice.cards?conveyorChosen:[...selected];
  if(f.elements.value)args.value=c.choice.kind==='duel-start'?f.elements.value.value==='1':Number(f.elements.value.value);
 }
 if(f.id==='cv-urgent-form'){action='urgent';args.ids=[...f.querySelectorAll('[name=urgentIds]')].map(x=>x.value);if(f.elements.effect.value==='discard')args.ids.push(...[...f.querySelectorAll('[name=discardIds]:checked')].map(x=>x.value));args.direction=f.elements.direction.value;const wild=wildcardPayload();if(wild!==undefined)args.wildcard=typeof wild==='object'?Object.fromEntries(Object.entries(wild).filter(([id])=>args.ids.includes(id))):wild;}
 if(f.elements.target&&f.elements.target.value!=='')args.target=Number(f.elements.target.value);
 if(f.elements.effect)args.effect=f.elements.effect.value;
 if(f.elements.suit)args.suit=f.elements.suit.value;
 if(f.elements.markRank0&&args.effect==='release'){args.ranks=Array.from({length:7},(_,i)=>Number(f.elements['markRank'+i].value));args.suits=Array.from({length:7},(_,i)=>f.elements['markSuit'+i].value);}
 if(await gameAction(action,args)){resetConveyorSelection();conveyorChosen=[];if(f.id!=='cv-choice-form')closeModal();renderedKey='';render();}
 }catch(error){const target=f.querySelector('.form-error');if(target)target.textContent=error.message;else toast(error.message);}
});

function conveyorRules(){showModal('cv-rules',`<h2>传送带 · S0 V0.10.1</h2><p>四人各自为战，固定 110 张牌，不使用爆牌、进贡和升变，沿用 4A4A4 标准牌型。每人独立记录等级，第一名升两级、第二名升一级，其他人不变；下一局使用第一名的主牌。打到只剩一人时结算，不按对家提前结束。行动后自动发一张；前两次轮到自己时，出空仍继续发一张；第三次起走完手牌与未出展示区才可获胜。只有使用急牌轮换手牌时，才将所有已打出的非急牌洗混后放回牌堆底。4A4 类组合按牌面上的 4 和 A 判定。</p><p>技能可以重复选择。出牌、不出或被跳过后进入抽牌阶段，默认抽一张，随后扣除已生效的回合效果。插入勾、点、叉也算一次行动。前两次出空仍抽一张，第三次起清空手牌和未出展示区后即走完。</p><p>2 为 15，主牌为 16。判定时小王为 20、大王为 25、急牌为 2。主牌参与顺子时按原点数。判定牌弃置，不算真实出牌。</p><p>正式对局中，急牌可以在别人的出牌阶段插入，但不能打断选牌或判定。急牌可加牌、弃牌、禁手、免抽、弃最大牌、封禁技能三回合、强化判定，或轮换并销毁。每张急牌最多不废弃使用三次，第四次必须轮换。封禁只暂停技能效果，印记保留。</p>${(state.room.skills||[]).map(s=>`<details><summary>${esc(s.name)} · ${s.deal} 选 ${s.keep}</summary><p class="skill-description">${esc(s.text)}</p></details>`).join('')}`);}
