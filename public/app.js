'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {conveyor:'传送带',landlord:'斗地主',standard:'4A4A4',trio:'4A4A4 · 三人',basic:'4A4 · 基础'};
const ranks = {3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'10',11:'J',12:'Q',13:'K',14:'A',15:'2',16:'小王',17:'大王',18:'急'};
for(let n=3;n<=15;n++)ranks[n+20]=ranks[n];
const wildRanks = () => Array.from({length:13},(_,i)=>i+3);
const suits = {S:'♠',H:'♥',C:'♣',D:'♦',T:'Δ',J:'✦',U:'↗'};
let state = {user:null,room:null}, selected = new Set(), wildcardMap = {}, hintIndex = 0, hintMoves = [], renderedKey = '', lastPhase = '', busy = false, authTab = 'login', createMode = 'landlord', modalKind = '';
let mutationSequence=0;
let responseKey='', pollTimer, toastTimer, screen='home', settingsTab='account', connectionLost=false;
let partyMode=false, partyTable, partyPlayNumber=0, partyBurst;
try {partyMode=localStorage.getItem('vgc-party-mode')==='1';} catch {}

function observePartyPlay(room){
  const game=room?.game, table=game?tableKey(room):null;
  const playNumber=game?.playNumber??0;
  if(table!==partyTable){
    partyTable=table;partyPlayNumber=playNumber;
    partyBurst?.remove();
    return;
  }
  if(playNumber<=partyPlayNumber)return;
  partyPlayNumber=playNumber;
  if(!partyMode||document.hidden||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const board=$('#view .board')||$('#view .result-stage');
  if(!board)return;
  partyBurst?.remove();
  const burst=document.createElement('div'), rect=board.getBoundingClientRect();
  partyBurst=burst;
  burst.className='party-burst';
  burst.setAttribute('aria-hidden','true');
  Object.assign(burst.style,{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px'});
  const colors=['#f3ba50','#e96a93','#55c6bf','#a394f5','#ed804e'];
  const spread=Math.min(rect.width*.42,rect.height*.8,235);
  for(let i=0;i<24;i++){
    const piece=document.createElement('i');
    const angle=i*2*Math.PI/24, distance=spread*(.5+Math.random()*.5);
    const x=Math.cos(angle)*distance, y=Math.sin(angle)*distance;
    piece.style.backgroundColor=colors[i%colors.length];
    burst.append(piece);
    piece.animate([
      {transform:'translate(0,0)',opacity:0,offset:0},
      {opacity:1,offset:.15},
      {transform:`translate(${x}px,${y}px) rotate(${i*41}deg)`,opacity:.9,offset:.65},
      {transform:`translate(${x}px,${y+34}px) rotate(${i*52}deg)`,opacity:0,offset:1}
    ],{duration:680,easing:'cubic-bezier(.15,.72,.36,1)',fill:'both'});
  }
  document.body.append(burst);
  setTimeout(()=>burst.remove(),700);
}
const modal = $('#modal');
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3500); }
async function api(path, body) {
  const audio = gameAudio.canAnnounce()?'1':'0';
  const response = await fetch('/api/' + path, body === undefined ? {cache:'no-store',headers:{'X-Poker-Audio':audio}} : {method:'POST',headers:{'Content-Type':'application/json','X-Poker-Audio':audio},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请重试。');
  return data;
}
function markResponse(){
 const r=state.room,g=r?.game,response=g?.response;
 const key=response?`${r.code}/${r.matchId}/${response.key}`:'';
 if(key===responseKey)return;
 responseKey=key;
 if(!selected.size&&response?.moves.length){const move=response.moves[0];selected=new Set(move.ids);wildcardMap=move.wildcard||{};if(g.conveyor)conveyorDouble=move.double||null;}
}
async function requestMutation(path,body,isCurrent=()=>true){
 const before=state.room,phase=before?.game?.phase,choice=JSON.stringify(before?.game?.conveyor?.choice);
 const defer=path==='action'&&['keep','confirm','choice'].includes(body.action);
 let queued=false;
 try{
  for(let attempt=0;;attempt++){
   if(!isCurrent())throw Error('操作已取消。');
   try{return await api(path,body);}catch(error){
    if(!defer||error.message!=='等待本次行动播报完成。'||attempt>=40)throw error;
    if(!queued){queued=true;toast('正在播报，结束后确认本次选择。');}
    await new Promise(resolve=>setTimeout(resolve,250));if(!isCurrent())throw Error('操作已取消。');await sync();
    if(state.room?.code!==before.code||state.room?.matchId!==before.matchId||state.room?.game?.phase!==phase||body.action==='choice'&&JSON.stringify(state.room?.game?.conveyor?.choice)!==choice)throw Error('选择已更新，请重新确认。');
    body={...body,revision:state.room.revision};
   }
  }
 }finally{if(queued){clearTimeout(toastTimer);$('#toast').classList.remove('show');}}
}
async function mutation(path, body = {}) {
  if (busy&&!['leave','resign'].includes(path)) return;
  const sequence=++mutationSequence;
  busy = true;
  try { const result = await requestMutation(path,body,()=>sequence===mutationSequence);if(sequence!==mutationSequence)return; if ('room' in result) {if(['leave','resign'].includes(path)&&!result.room){screen='home';closeModal();window.scrollTo({top:0,behavior:'instant'});} state.room = result.room; markResponse(); renderedKey = ''; render();if(result.room&&['create','join','watch','match','start'].includes(path)){clearTimeout(toastTimer);$('#toast').classList.remove('show');window.scrollTo({top:0,behavior:'instant'});}} await sync(); return result; }
  catch(e) {if(sequence===mutationSequence){const error=modal.open?$('.form-error',modal):null;if(error)error.textContent=e.message;else toast(e.message);await sync();}}
  finally {if(sequence===mutationSequence)busy = false;}
}
async function sync() {
  try {
    const next = await api('state');
    connectionLost=false;updateConnection();
    const oldRoom = state.room?.code, oldMatch = state.room?.matchId;
    state = next;
    if (oldRoom !== state.room?.code || oldMatch !== state.room?.matchId) {selected.clear(); wildcardMap={};conveyorDouble=null;}
    const available = new Set(state.room?.game?.hand.map(c=>c.id) || []);
    selected = new Set([...selected].filter(id=>available.has(id)));
    markResponse();
    if(cardSweep){renderAfterSweep=true;gameAudio.observe(state.room);return;}
    render();
  } catch {connectionLost=true;updateConnection();}
}
function updateConnection(){const banner=$('#connection-notice');if(banner)banner.hidden=!connectionLost;}
async function poll() {await sync(); pollTimer = setTimeout(poll, document.hidden ? 2500 : 850);}
function showModal(kind, content) {modalKind=kind; $('#modal-content').innerHTML=content; if(!modal.open) modal.showModal();}
function closeModal() {modal.close(); modalKind='';}
function requireUser(fn) {if(!state.user) {showAuth();return;} fn();}
function card(c, interactive=false, g=null) {
  const red = c.suit==='H'||c.suit==='D'||c.rank===17;
  const wild = g && !['landlord','basic'].includes(g.mode) && c.suit==='S' && c.rank===14;
  const urgentUses=g?.mode==='conveyor'&&((c.effective??c.rank)===18||c.urgentUses)?c.urgentUses||0:null;
  const label = `${ranks[c.rank]}${suits[c.suit]}`+(urgentUses===null?'':`，已使用 ${urgentUses} 次${urgentUses>=3?'，下次必须轮换销毁':''}`);
  return `<${interactive?'button':'div'} class="card ${red?'red':''} ${c.rank>=16?'joker':''} ${selected.has(c.id)&&interactive?'selected':''} ${wild?'wild':''} ${g&&g.mode!=='landlord'&&c.rank===g.main?'main-card':''}" ${interactive?`data-card="${esc(c.id)}" aria-pressed="${selected.has(c.id)}" aria-label="${esc(label)}${wild?'，混子':''}"`:''}><span class="card-rank">${ranks[c.rank]}</span><span class="card-suit">${c.rank>=16?'':suits[c.suit]}</span><span class="card-center">${c.rank>=16?(c.rank===18?'↗':'✦'):suits[c.suit]}</span>${c.effective&&c.effective!==c.rank?`<span class="effective-rank">→ ${g?.mode==='conveyor'&&c.effective===g.main?'主':''}${ranks[c.effective]}</span>`:''}${urgentUses===null?'':`<span class="urgent-count" title="${esc(label)}">${urgentUses}/3</span>`}<span class="card-bottom">${ranks[c.rank]}${suits[c.suit]}</span></${interactive?'button':'div'}>`;
}
function render() {
  const u=state.user,r=state.room,g=r?.game;
  document.body.classList.toggle('home-screen',!r&&screen==='home');
  document.body.classList.toggle('in-game',!!g);
  document.body.classList.toggle('landlord-game',r?.mode==='landlord'&&!!g);
  document.body.classList.toggle('standard-game',r?.mode==='standard'&&!!g);
  document.body.classList.toggle('live-table',g?.phase==='play');
  document.body.classList.toggle('conveyor-game',g?.mode==='conveyor');
  document.body.classList.toggle('round-over',g?.phase==='over');
  document.body.classList.toggle('tribute-phase',g?.phase==='tribute');
  document.body.classList.toggle('opening-phase',['setup','rps','draft','tribute'].includes(g?.phase));
  document.body.classList.toggle('hand-choice-phase',!!g?.conveyor?.choice&&!g.conveyor.choice.cards&&conveyorHandChoices.has(g.conveyor.choice.kind));
  const key = JSON.stringify([u,r,screen,settingsTab,state.checkin,state.preferences,state.features?.playtest,screen==='create'?state.matchCounts:null]);
  if(key===renderedKey){gameAudio.observe(r);return;}
  renderedKey=key;
  const handScroll=$('.hand')?.scrollLeft||0;
  const previousTable=$('#view [data-table]')?.dataset.table;
  const currentTable=r?(g?tableKey(r):'prep/'+r.code):null;
  const revealed=previousTable===currentTable?$('#view .reveal-sheet[open]')?.id:null;
  const openPanels=previousTable===currentTable
    ? new Map($$('#view [data-table-panel]').map(panel=>[panel.dataset.tablePanel,panel.open])) : new Map();
  const tableFocus=previousTable===currentTable
    ? document.activeElement?.closest('#view :is(.hand [data-card], .action-dock [data-action], [data-table-panel] > summary)') : null;
  const choiceForm=$('#cv-choice-form');
  const choiceDraft=choiceForm?{key:choiceForm.dataset.choiceKey,values:[...new FormData(choiceForm)]}:null;
  const joinInput=$('#join-code'); const joinValue=joinInput?.value; const joinFocus=document.activeElement===joinInput;
  if(!r) $('#view').innerHTML=screen==='home'?lobby():screen==='settings'?settingsScreen():flowScreen();
  else if(!g) $('#view').innerHTML=waiting(r);
  else $('#view').innerHTML=table(r,g);
  if(revealed)openRevealedHand(document.getElementById(revealed));
  if(joinValue!==undefined && $('#join-code')){$('#join-code').value=joinValue; if(joinFocus)$('#join-code').focus();}
  if($('#view #playtest-panel'))mountPlaytest($('#view #playtest-panel'));
  const nextChoice=$('#cv-choice-form');
  if(choiceDraft&&nextChoice?.dataset.choiceKey===choiceDraft.key){
    for(const [name,value] of choiceDraft.values){
      const options=[...nextChoice.querySelectorAll('input[type="radio"]')].filter(input=>input.name===name);
      const option=options.find(input=>input.value===value&&!input.disabled);
      if(option)option.checked=true;
      else if(!options.length){const field=nextChoice.elements.namedItem(name);if(field)field.value=value;}
    }
  }
  if($('.hand'))$('.hand').scrollLeft=handScroll;
  for(const panel of $$('#view [data-table-panel]'))if(openPanels.has(panel.dataset.tablePanel))panel.open=openPanels.get(panel.dataset.tablePanel);
  if($('.log-entries'))$('.log-entries').scrollTop=$('.log-entries').scrollHeight;
  const hand=$('.hand-area');
  if(hand&&g?.phase!=='over'&&!$('.action-feedback')){
    const message=r.audioWaiting?'正在播报，可以先选牌。':r.players[r.seat]?.autoplay?'规则 AI 托管中，可随时取消':'';
    if(message)hand.insertAdjacentHTML('afterbegin',`<p class="action-status" role="status">${message}</p>`);
  }
  if(r?.mode==='conveyor')conveyorAfterRender();
  if(g?.priorityClock&&g.priorityClock.seat!==r.seat)$$('[data-action]').filter(b=>b.dataset.action==='pass'||b.dataset.action==='play'&&!g.conveyor).forEach(b=>b.disabled=true);
  if(r?.audioWaiting){
    const actions=new Set(['start','play','pass','bid','reveal','confirm','promote','rps','tribute-pick','tribute-return','gift-player']);
    $$('[data-action]').filter(b=>actions.has(b.dataset.action)).forEach(b=>b.disabled=true);
  }
  if(r?.players[r.seat]?.autoplay){
    const actions=new Set(['play','pass','hint','bid','reveal','confirm','promote','rps','tribute-pick','tribute-return','gift-player']);
    $$('[data-action]').filter(b=>actions.has(b.dataset.action)).forEach(b=>b.disabled=true);
  }
  if($('.hand-area')&&!r.spectator)selectionUpdate();
  if(tableFocus){
    const data=tableFocus.dataset;
    const target=data.card?$$('.hand [data-card]').find(b=>b.dataset.card===data.card)
      : data.action?$(`.action-dock [data-action="${data.action}"]`)
      : $$('#view [data-table-panel]').find(p=>p.dataset.tablePanel===tableFocus.parentElement.dataset.tablePanel)?.querySelector('summary');
    target?.focus({preventScroll:true});
  }
  if(g && lastPhase!==g.phase){if(!lastPhase||lastPhase==='over'||['play','over'].includes(g.phase))window.scrollTo({top:0,behavior:'instant'});if(g.phase==='over'){clearTimeout(toastTimer);$('#toast').classList.remove('show');}if(lastPhase==='rps'&&g.phase==='play')toast('猜拳获胜：'+r.players[g.turn].name+'，先出牌。');hintMoves=[];hintIndex=0;lastPhase=g.phase;}
  if(!g)lastPhase='';
  observePartyPlay(r);
  gameAudio.observe(r);

}
function lobby() {
  const u=state.user;
  return `<section class="game-home"><div class="home-copy"><h1 class="home-title">VGC<span>扑克牌俱乐部</span></h1><div class="title-splash">${esc(titleSplash)}</div><div class="main-menu"><button class="main-menu-item" data-action="open-create"><span class="menu-label">创建房间</span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="open-single"><span class="menu-label">单人模式</span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="settings"><span class="menu-label">设置</span><span class="menu-arrow">↗</span></button></div><div class="home-bottom"><span>${u?esc(u.name)+' · '+esc(u.rank)+' / '+u.points+' 积分':''}</span><button class="text-button" data-action="${u?'leaderboard':'auth'}">${u?'积分榜':'登录 / 注册'} ↗</button>${u?dailyCheckinButton():''}</div></div><div class="home-scene" aria-hidden="true"><div class="sketch-ring ring-one"></div><div class="sketch-ring ring-two"></div><div class="home-card-fan">${[['4','♣'],['A','♥'],['4','♠'],['A','♦'],['4','♣']].map(([r,s],i)=>`<div class="home-art-card ${s==='♥'||s==='♦'?'red':''}" data-index="${i}"><span>${r}<small>${s}</small></span><b>${s}</b><i>${r}<small>${s}</small></i></div>`).join('')}</div></div></section>`;
}
function dailyCheckinButton(){
 const checkin=state.checkin;
 if(!checkin)return '';
 return `<button class="text-button" data-action="checkin" ${checkin.checked?'disabled':''} title="每天随机获得 10–30 积分，连续签到第 7 天起翻倍">${checkin.checked?`已签到 · +${checkin.reward} · 连续 ${checkin.streak} 天`:'每日签到'}</button>`;
}
function flowScreen(){
 const single=screen==='single';
 return `<div class="flow-heading"><button class="menu-back" data-action="home">← 返回主菜单</button><h1>${single?'单人模式':'创建房间'}</h1></div><div class="mode-layout"><section class="mode-grid">${[['landlord','01','经典斗地主','三人 / 54 张','叫分争地主，联手定胜负。','♠'],['standard','02','4A4A4 标准版','四人 / 110 张 / 2.4','勾叉点压，见招拆招。','4A'],['trio','03','4A4A4 三人版','三人 / 86 张','各自为战，争先出完。','♧'],['basic','04','4A4 基础版','四人 / 54 张','基础勾叉，三张起炸。','4'],['conveyor','05','传送带','四人 / 个人 / 技能','', '↻']].map(([m,,t,n,,mark])=>`<section class="mode-choice"><button class="mode-card" data-action="choose-mode" data-mode="${m}"><span class="mode-symbol">${mark}</span><h2>${t}</h2><div class="mode-foot"><small>${n}</small><span>选择 →</span></div></button>${single?'':`<button class="secondary match-button" data-action="match" data-mode="${m}" ${!(state.matchCounts?.[m])?'disabled':''}>匹配 · ${state.matchCounts?.[m]||0} 个房间</button>`}</section>`).join('')}</section><aside class="flow-aside">${single?`<div class="side-panel"><h3>加入房间</h3><form id="join-form"><input id="join-code" class="join-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="— — —" aria-label="六位房间号" autocomplete="off"><button class="secondary full" type="submit">加入房间 →</button></form><div class="divider"></div><button class="text-button" data-action="settings-api">模型 API 设置 ↗</button><p>单人模式不计积分。</p></div>`:`<div class="side-panel"><h3>加入房间</h3><form id="join-form"><input id="join-code" class="join-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="— — —" aria-label="六位房间号" autocomplete="off"><button class="secondary full" type="submit">加入房间 →</button><button class="secondary full" type="button" data-action="watch">观战 →</button></form><div class="divider"></div><p>仅全真人对局计分。</p></div>`}</aside></div>`;
}
function settingsScreen(){
 const u=state.user, pref=state.preferences||{};
 const tabs=[['account','账号信息'],['audio','声音'],['effects','特效'],['api','模型 API'],['archive','积分与战绩']];
 if(u&&state.features?.playtest)tabs.push(['playtest','自动对局']);
 let content='';
 if(settingsTab==='audio')content=`<h2>声音</h2><div class="audio-controls">${[['effects','音效'],['music','音乐'],['voice','语音']].map(([key,label])=>`<label><span>${label}<output id="volume-${key}">${Math.round(gameAudio.volumes[key]*100)}%</output></span><input type="range" min="0" max="100" value="${Math.round(gameAudio.volumes[key]*100)}" data-volume="${key}" aria-label="${label}音量"></label>`).join('')}</div><div class="phase-actions"><button class="secondary" data-action="preview-effect">试听音效</button><button class="secondary" data-action="preview-voice">试听语音</button></div>`;
 else if(settingsTab==='effects')content=`<h2>特效</h2><label class="party-setting"><input type="checkbox" data-party-mode ${partyMode?'checked':''}>派对狂欢</label><p class="modal-desc">每次成功出牌时，在牌桌上撒彩纸。</p>`;
 else if(!u)content='<h2>请先登录</h2><p class="modal-desc">登录后管理账号、保存模型 API 和查看战绩。</p><button class="primary" data-action="auth">登录 / 注册 →</button>';
 else if(settingsTab==='account')content=`<h2>账号信息</h2><p class="modal-desc">${esc(u.rank)} · ${u.points} 积分 · ${u.games} 场真人对局</p><form class="form" id="account-form"><label>玩家昵称<input name="name" value="${esc(u.name)}" required minlength="2" maxlength="18" autocomplete="username"></label><label>当前密码<input name="currentPassword" type="password" required autocomplete="current-password" placeholder="保存信息时验证身份"></label><label>新密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空表示保留当前密码"></label><p class="form-note">修改密码后，其他设备的登录会话将退出。</p><p class="form-error"></p><button class="primary" type="submit">保存账号信息 →</button></form><div class="divider"></div><button class="text-button" data-action="logout">退出账号 ↗</button>`;
 else if(settingsTab==='api')content=`<h2>模型 API</h2><p class="modal-desc">${pref.configured?'已配置 · 密钥已保存到本次服务的内存中':'兼容 Chat Completions 的 HTTPS API。'}</p><form class="form" id="api-settings-form"><label>API 基础地址<input name="endpoint" type="url" required value="${esc(pref.endpoint||'')}" placeholder="https://api.example.com/v1"></label><label>模型名称<input name="model" required maxlength="100" value="${esc(pref.model||'')}" placeholder="模型 ID"></label><label>API 密钥<input name="key" type="password" ${pref.configured?'':'required'} autocomplete="off" placeholder="${pref.configured?'密钥已保存；留空表示不更换':'输入你的 API Key'}"></label><p class="form-note">模型只看到自己的手牌与公开局面。无效回答或请求失败时使用规则 AI。密钥不会返回浏览器或写入数据库，服务重启后需要重新配置。模型提供商可能按请求收费。</p><p class="form-error"></p><button class="primary" type="submit">保存模型配置 →</button></form>${pref.configured?'<div class="divider"></div><button class="text-button" data-action="clear-api">清除 API 配置 ↗</button>':''}`;
 else if(settingsTab==='playtest'&&state.features?.playtest)content='<h2>自动对局</h2><div id="playtest-panel"></div>';
 else content=`<h2>积分与战绩</h2><p class="modal-desc">仅全真人对局计分。</p><div class="profile-stats"><div><strong>${u.points}</strong><small>${u.rank}</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div class="phase-actions"><button class="secondary" data-action="profile">最近战绩 →</button><button class="secondary" data-action="leaderboard">查看积分榜 →</button></div>`;
 return `<div class="flow-heading"><button class="menu-back" data-action="home">← 返回主菜单</button><h1>设置</h1></div><div class="settings-layout"><nav class="settings-tabs">${tabs.map(([k,t])=>`<button class="${settingsTab===k?'active':''}" data-action="settings-tab" data-tab="${k}">${t}<span>→</span></button>`).join('')}<div class="divider"></div><button data-action="rules">玩法手册 <span>↗</span></button></nav><section class="settings-content">${content}</section></div>`;
}
function showSettingsModal(){showModal('settings',settingsScreen(),'SETTINGS');mountPlaytest($('#modal #playtest-panel'));}
function navigate(next){screen=next;renderedKey='';render();window.scrollTo({top:0});}

function roomHeading(r,playing=false,history=''){const g=r.game;const promoted=g&&Object.values(g.promotions).includes(g.main);const mainBadge=playing&&r.mode!=='landlord'?`<span class="main-indicator">主牌 <b>${ranks[g.main]}</b>${promoted?' · 升变':''}</span>`:'';if(r.replay)return mainBadge?`<div class="replay-main">${mainBadge}</div>`:'';return `<div class="room-heading"><div><h1>${esc(names[r.mode])}<span class="muted"> · ${r.spectator?'观战':playing?'对局':'准备室'}</span></h1>${mainBadge}</div><div class="room-heading-actions">${history}<button class="room-number" data-action="copy"><small>房间号</small>${r.code} <small>⧉</small></button><button class="secondary room-exit" data-short-label="${r.spectator?'退出':playing&&g.phase!=='over'?'结束':'离开'}" data-action="${playing&&r.game.phase!=='over'&&!r.spectator?'resign':'leave'}">${r.spectator?'退出观战':playing&&r.game.phase!=='over'?(r.single?'结束本局':'返回大厅'):'离开房间'} ↗</button>${playing&&r.game.phase!=='over'&&!r.spectator&&r.canLeave?'<button class="text-button" data-action="leave">离开房间 ↗</button>':''}</div></div>`;}
function waiting(r) {
  if(r.mode==='conveyor')return conveyorWaiting(r);
  if(r.spectator)return roomHeading(r)+`<div class="prep-room">${preparationSeats(r)}<p>等待房主开始</p></div>`;
  const host=r.host===state.user.id;
  const rules={landlord:'三人 · 54 张 · 叫分抢地主',trio:'三人 · 86 张 · 个人争先',basic:'四人 · 54 张 · 对座组队',standard:'四人 · '+(r.options.dlc?'150':'110')+' 张 · 对座组队'};
  return roomHeading(r)+`<div class="prep-room">${preparationSeats(r)}<div class="prep-controls"><p>${rules[r.mode]} · ${r.rated?'计入积分':'练习对局'}</p><button class="primary" data-action="start" ${!host||r.players.length!==r.capacity?'disabled':''}>${host?'开始对局 →':'等待房主开始'}</button><button class="text-button" data-action="rules">本桌玩法</button></div></div>`;

}
function table(r,g) {
  if(r.mode==='conveyor')return conveyorTable(r,g);
  const me=r.seat??0;
  let ownProfile='';
  const positions=r.capacity===3?['bottom','left','right']:['bottom','left','top','right'];
  const seats=r.players.map((p,s)=>{
    const relative=(s-me+r.capacity)%r.capacity;
    const finish=g.finished.indexOf(s);
    const role=g.mode==='landlord'&&g.landlord!=null?(g.landlord===s?'地主':'农民'):'';
    const played=g.seatPlays?.[s]||(!g.seatPlays&&g.lastSeat===s?{...g.last,order:1}:null);
    const playNumber=g.playNumber??1;
    const playStatus=g.phase==='play'&&g.priorityClock?.seat===s?`<div class="playing priority-clock" role="status">${r.replay?'优先管牌':g.priorityClock.paused?'优先管牌 · 计时暂停':'优先管牌 '+g.priorityClock.remaining+' 秒'}</div>`:g.phase==='play'&&g.priorityResponder===s?'<div class="playing priority-clock" role="status">优先管牌</div>':g.phase==='play'&&!g.priorityClock&&g.priorityResponder==null&&g.turn===s?'<div class="playing" role="status">出牌中...</div>':'';
    const playedCards=['setup','rps'].includes(g.phase)?`<div class="seat-play opening-display">${openingDisplay(g,g.reveals.includes(s),g.ready.includes(s))}</div>`:played||playStatus?`<div class="seat-play ${played&&!played.passed&&played.order===playNumber?'latest':played&&!playStatus?'older':''}">${playStatus}${played?seatPlayCards(played,g):''}</div>`:'';
    const own=!r.spectator&&!r.replay&&s===r.seat;
    const turn=['play','bid'].includes(g.phase)&&(g.priorityClock?.seat??g.priorityResponder??g.turn)===s;
    const portrait=`<div class="seat-portrait">${playerAvatar(p,s)}${role?`<small class="seat-role">${role}</small>`:''}</div>`;
    const meta=`<div class="seat-meta">${g.urgentLast.includes(s)?'急牌末名':g.phase==='over'&&g.counts[s]>0?'剩 '+g.counts[s]+' 张':finish>=0?'第 '+(finish+1)+' 名':g.counts[s]+' 张牌'}${p.autoplay?'<span class="autoplay-status">托管中</span>':''}${!p.connected?' · 离线':''}</div>`;
    if(own)ownProfile=`<div class="own-player ${turn?'turn':''}" data-own-seat="${s}">${portrait}${meta}</div>`;
    return `<div class="seat ${positions[relative]} ${own?'own-seat':''} ${turn?'turn':''} ${finish>=0?'finished':''}">${own?'':portrait}<div>${own?'':meta}${seatRevealedHand(r,g,s)}</div>${playedCards}${r.bubbles?.[s]?`<div class="speech-bubble" role="status" aria-label="${esc(p.name)}的发言">${esc(r.bubbles[s])}</div>`:''}</div>`;
  }).join('');
  let center='',openingActions='';
  if(g.phase==='bid') center=`<div class="table-prompt">${g.turn===me?'轮到你叫分':esc(r.players[g.turn].name)+' 正在叫分'}</div><p class="table-sub">当前最高叫分 ${g.bid} · 三分直接成为地主</p>${g.turn===me?`<div class="phase-actions">${[0,1,2,3].map(n=>`<button class="${n===3?'primary':'secondary'}" data-action="bid" data-value="${n}" ${n&&n<=g.bid?'disabled':''}>${n?n+' 分':'不叫'}</button>`).join('')}</div>`:''}`;
  else if(g.phase==='setup') {
    const count={};g.hand.forEach(c=>count[c.rank]=(count[c.rank]||0)+1);
    const promotions=g.mode==='basic'?[]:Object.keys(count).filter(k=>Number(k)<16&&count[k]>=6);
    center=`<div class="table-prompt">${g.openingFirst===null?'开局亮牌':'开局升变'}</div>${openingCountdown(g)}<p class="table-sub">${g.openingFirst===null?'无人亮牌则随机先手':esc(r.players[g.openingFirst].name)+'先出'}</p>`;
    if(!r.spectator&&g.confirmationSeats?.includes(me))openingActions=`<div class="phase-actions opening-actions">${g.openingFirst===null&&g.hand.some(c=>c.suit==='S'&&c.rank===3)&&!g.reveals.includes(me)?'<button class="secondary" data-action="reveal">亮黑桃 3</button>':''}${promotions.map(k=>`<button class="secondary" data-action="promote" data-rank="${k}" ${Number(k)===g.promotions[me]?'disabled':''}>升变 ${ranks[k]}</button>`).join('')}</div>`;
  } else if(g.phase==='rps') {
    center=`<div class="table-prompt">猜拳定先手</div>${openingCountdown(g)}`;
    openingActions=rpsActions(r,g,g.reveals.includes(me),g.ready.includes(me));
  }
  else if(g.phase==='tribute') {
    const t=g.tribute, offer=t.offers.find(o=>o.recipient===me&&!o.returned), canChoose=t.stage==='choose'&&t.receivers.includes(me)&&!t.offers.some(o=>o.recipient===me);
    center='<div class="table-prompt">进贡</div>';
    const waiting=t.offers.filter(o=>o.recipient!==null&&!o.returned).map(o=>esc(r.players[o.recipient].name)).join('、');
    openingActions=`<section class="tribute-panel"><h3>${canChoose?'选择一张贡牌':offer?'选一张手牌返还':'进贡进行中'}</h3><p>${canChoose?'收下贡牌后，返还一张手牌。':offer?'还给 '+esc(r.players[offer.donor].name):t.stage==='return'?'等待 '+waiting+' 还牌':'等待队友选择贡牌'}</p><div class="tribute-offers">${t.offers.map(o=>`<button class="secondary tribute-card ${['H','D'].includes(o.card.suit)||o.card.rank===17?'red':''}" data-action="tribute-pick" data-seat="${o.donor}" ${!canChoose||o.recipient!==null?'disabled':''}><span>${ranks[o.card.rank]}${suits[o.card.suit]}</span><small>${esc(r.players[o.donor].name)}${o.recipient!==null?' → '+esc(r.players[o.recipient].name):''}</small></button>`).join('')}</div></section>`;
  }
  else if(g.phase==='play') center=g.mode==='landlord'&&!g.last&&g.bottom.length?`<div class="bottom-cards">${g.bottom.map(c=>`<span class="mini-card ${['H','D'].includes(c.suit)?'red':''}">${ranks[c.rank]}${suits[c.suit]}</span>`).join('')}</div>`:'';
  else center='<div class="table-prompt">本局已结束</div>';
  if(r.spectator&&!['setup','rps','over'].includes(g.phase)&&!(r.replay&&g.phase==='play'))center=['bid','tribute'].includes(g.phase)?'<div class="table-prompt">'+({bid:'正在叫分',tribute:'进贡中'})[g.phase]+'</div>':'';
  const canPlay=!r.spectator&&g.phase==='play'&&!g.finished.includes(me)&&!r.players[me].autoplay;
  const canReturn=!r.spectator&&!r.players[me].autoplay&&g.phase==='tribute'&&g.tribute.stage==='return'&&g.tribute.offers.some(o=>o.recipient===me&&!o.returned);
  const remainingHands=g.remainingHands?`<div class="settlement-hands">${g.remainingHands.map((hand,s)=>`<section class="settlement-hand"><h3>${esc(r.players[s].name)} <small>剩余 ${hand.length} 张</small></h3><div class="settlement-cards">${hand.length?hand.map(c=>`<span class="settlement-card ${['H','D'].includes(c.suit)||c.rank===17?'red':''}">${ranks[c.rank]}${suits[c.suit]}</span>`).join(''):'<span class="muted">已出完</span>'}</div></section>`).join('')}</div>`:'';
  const result=g.phase==='over'?r.spectator?`<div class="result-banner"><h2>本局结束</h2><p>${g.winner.map(s=>esc(r.players[s].name)).join('、')} 获胜</p>${remainingHands}</div>`:`<div class="result-banner"><h2>${g.winner.includes(me)?'胜利':'失败'}</h2><p>${g.winner.map(s=>esc(r.players[s].name)).join('、')} 获胜<br>${r.rated?'真人对局 · '+(g.winner.includes(me)?'+':'−')+(g.mode==='landlord'?24:20)+' 积分':'练习对局 · 不结算积分'}${g.mode!=='landlord'?(g.roundComplete?'<br>本轮结束，下轮主牌 3':'' )+'<br>出完顺序：'+(g.finished.filter(s=>g.counts[s]===0).map(s=>esc(r.players[s].name)).join(' → ')||'尚无人出完'):''}</p>${remainingHands}${r.host!==state.user.id?'<p class="table-sub">等待房主开始下一局。</p>':''}</div>`:'';
  const options=!['landlord','basic'].includes(g.mode)&&g.hand.some(c=>c.rank===14&&c.suit==='S')?'<button class="text-button" data-action="declare-wild" hidden>指定赖子</button>':'';
  const controls=canReturn
    ? `<div class="hand-controls"><button class="text-button" data-action="deselect">清空<span class="keyboard-shortcut"> · Esc</span></button><button class="primary" data-action="tribute-return" ${selected.size!==1?'disabled':''}>还牌<span class="keyboard-shortcut"> · Enter</span></button></div>`
    : canPlay?actionDock(options):'';
  const handArea=r.spectator?'':`<section class="hand-area"><div class="hand-top">${ownProfile}<div class="hand-tools">${handTools(r)}</div></div>${openingActions}<div class="hand ${g.hand.length>23?'dense':''}">${g.hand.map(c=>card(c,canPlay||canReturn,g)).join('')}</div>${controls}</section>`;
  const summary=g.mode==='landlord'?`地主叫分 <b>${g.bid}</b>`:g.mode==='trio'?'三人个人争先':`${r.spectator?'一队':'我方'} <b>${g.scores[me%2]}</b> · ${r.spectator?'二队':'对方'} <b>${g.scores[1-me%2]}</b>`;
  const history=tableHistory(g,`${summary}<br>${r.rated?'计入积分与段位':'练习 · 不计积分'}`,r.replay);
  if(result&&!r.replay)return roomHeading(r,true,history)+settlement(r,result);
  return roomHeading(r,true,history)+`<div class="table-layout"><section class="board" data-table="${esc(tableKey(r))}">${seats}<div class="table-center">${center}</div></section>${r.replay?history:''}</div>${handArea}${publicHandsPanel(r,g)}${r.replay?result:''}`;
}

function showHandButton(r,g){return g.phase!=='over'?`<button class="secondary" data-action="show-hand" ${(g.publicHands||[]).some(h=>h.owner===r.seat)?'disabled':''}>${(g.publicHands||[]).some(h=>h.owner===r.seat)?'已明牌':'明牌'}</button>`:'';}
function openingCountdown(g){
  const clock=g.openingClock;
  return clock?`<p class="opening-clock">${clock.waiting?'发牌或播报中':clock.remaining+' 秒'}</p>`:'';
}
function openingDisplay(g,revealed,submitted){
  const state=g.phase==='rps'&&revealed?`<div class="seat-play-label">${submitted?'已出拳':'待出拳'}</div>`:'';
  return state+(revealed?'<div class="seat-play-cards" aria-label="亮出黑桃 3"><span class="seat-play-card"><b>3</b><small>♠</small></span></div>':'');
}
function rpsActions(r,g,eligible,submitted){
  if(r.spectator)return '';
  if(!eligible||submitted)return `<p class="opening-wait">${submitted?'已出拳，等待其他玩家':'亮牌玩家正在猜拳'}</p>`;
  const report=[...g.log].reverse().find(text=>text.startsWith('猜拳平局')||text.startsWith('猜拳胜者'));
  const buttons=[['rock','石头'],['scissors','剪刀'],['paper','布']].map(([v,n])=>`<button class="secondary" data-action="rps" data-value="${v}">${n}</button>`).join('');
  return (report?`<p class="rps-feedback" role="status">${esc(report)}</p>`:'')+`<div class="phase-actions opening-actions">${buttons}</div>`;
}
function roundActions(r){return `<nav class="round-actions" aria-label="本局结束操作">${!r.spectator?`<button class="primary" data-action="start" ${r.host!==state.user.id?'disabled':''}>${r.host===state.user.id?'再来一局 →':'等待房主开局'}</button>`:''}<button class="secondary" data-action="leave">回到主菜单</button></nav>`;}
function settlement(r,result,options=''){
  return `<section class="result-stage" data-table="${esc(tableKey(r))}"><div class="score-sheet"><div class="score-scroll">${result}${options}</div>${roundActions(r)}</div></section>`;
}
function preparationSeats(r){
  const capacity=r.capacity||4, host=!r.spectator&&r.host===state.user?.id;
  const positions=capacity===3?['bottom','left','right']:['bottom','left','top','right'];
  const seats=Array.from({length:capacity},(_,i)=>{
    const p=r.players[i], side=positions[(i-(r.seat??0)+capacity)%capacity];
    const skill=r.mode==='conveyor'&&(p?.skill||p?.botSkill);
    const detail=skill?conveyorSkill(skill)?.name:p?.bot&&r.mode==='conveyor'?'随机技能':p?.bot?(p.model?'模型 AI':'规则 AI'):p?.id===r.host?'房主':p?.connected?'已落座':'暂时离线';
    if(!p&&host)return `<button class="prep-seat ${side} vacant" data-action="invite-ai"><span class="avatar">＋</span><strong>邀请 AI</strong></button>`;
    return `<div class="prep-seat ${side}${p?'':' vacant'}">${p?playerAvatar(p,i):'<span class="avatar">＋</span><strong>空座位</strong>'}<small>${p?esc(detail):'等待加入'}</small>${host&&p?.bot?`<button class="seat-remove" data-action="remove" data-seat="${i}" aria-label="移除${esc(p.name)}">×</button>`:''}</div>`;
  }).join('');
  return `<div class="prep-map" data-table="prep/${esc(r.code)}"><div class="prep-count"><strong>${r.players.length}<small> / ${capacity}</small></strong><span>已入座</span></div>${seats}</div>`;
}
const avatarInitial=p=>Array.from(p.name)[0]||'·';
function playerAvatar(p,seat){
  return `<button type="button" class="avatar player-avatar" data-action="seat-profile" data-player-seat="${seat}" aria-label="查看${esc(p.name)}的玩家资料" aria-haspopup="dialog"><span aria-hidden="true">${esc(avatarInitial(p))}</span></button>`;
}
async function openPlayerProfile(r,seat){
  const p=r.players[seat], dialog=$('#seat-profile');
  const detail=dialog.querySelector('.seat-profile-detail');
  dialog.querySelector('.profile-suit').textContent=avatarInitial(p);
  dialog.querySelector('h2').textContent=p.name;
  dialog.querySelector('.profile-id').textContent=p.bot?(r.replay?'自动对局 AI':p.model?'模型 AI':'规则 AI'):'ID '+p.id;
  detail.textContent=p.bot?'AI 不计段位积分。':'正在读取积分…';
  const request=String(p.id);
  dialog.dataset.player=request;
  dialog.showModal();
  if(p.bot)return;
  try{
    const profile=p.id===state.user?.id?state.user:(await api('leaderboard?roomPlayer='+encodeURIComponent(p.id))).players.find(u=>u.id===p.id);
    if(!profile)throw Error('暂无该玩家的积分记录。');
    if(dialog.open&&dialog.dataset.player===request){
      detail.innerHTML=`<div class="profile-score"><strong>${esc(profile.points)}</strong> 积分</div><p>${esc(profile.rank)} · ${esc(profile.games)} 场 · ${esc(profile.wins)} 胜</p>`;
    }
  }catch(error){if(dialog.open&&dialog.dataset.player===request)detail.textContent=error.message;}
}
function tableKey(r){return r.code+'/'+r.matchId;}
function handTools(r){
  const autoplay=!!r.players[r.seat]?.autoplay;
  const control=r.game?.phase==='over'?'':`<button class="secondary" data-action="autoplay" aria-pressed="${autoplay}">${autoplay?'取消托管':'托管'}</button>`;
  return control+'<button class="secondary chat-button" data-action="chat-menu" aria-haspopup="dialog">发言</button><button class="secondary table-tools-button" data-action="table-tools" aria-haspopup="dialog">更多</button>';
}
function actionDock(options=''){
  return `<div class="action-dock">
    <div class="action-feedback" role="status" aria-live="polite">
      <strong data-turn-label></strong><span data-play-preview></span>
    </div>
    <div class="hand-controls">
      <div class="controls-left">${options}</div>
      <div class="controls-right">
        <button class="text-button" data-action="deselect">清空<span class="keyboard-shortcut"> · Esc</span></button>
        <button class="secondary" data-action="hint">提示</button>
        <button class="secondary" data-action="pass">不出</button>
        <button class="primary" data-action="play">出牌<span class="keyboard-shortcut"> · Enter</span></button>
      </div>
    </div>
  </div>`;
}
function seatPlayCards(play,g){
  if(play.passed)return `<span class="pass-mark">${play.kind==='不出'?'不出':`不出（${esc(play.kind)}）`}</span>`;
  const cards=[];
  play.cards.forEach((card,i)=>{
    const effective=play.ranks[i]??card.rank, effectiveSuit=play.suits?.[i]||card.suit;
    const existing=cards.find(c=>c.rank===card.rank&&c.suit===card.suit&&c.effective===effective&&c.effectiveSuit===effectiveSuit);
    if(existing)existing.count++;
    else cards.push({...card,effective,effectiveSuit,count:1});
  });
  return `<div class="seat-play-label">${esc(play.kind)}</div><div class="seat-play-cards">${cards.map(c=>{
    const changed=c.rank!==c.effective||c.suit!==c.effectiveSuit;
    const effectiveLabel=(g.mode==='conveyor'&&c.effective===g.main&&c.rank!==c.effective?'主':'')+ranks[c.effective]+(suits[c.effectiveSuit]||'○');
    return `<span class="seat-play-card ${['H','D'].includes(c.suit)||c.rank===17?'red':''}" title="${ranks[c.rank]}${suits[c.suit]||'○'}${changed?' → '+effectiveLabel:''}"><b>${ranks[c.rank]}${c.count>1?`<em>×${c.count}</em>`:''}</b><small>${suits[c.suit]||'○'}${changed?'→'+effectiveLabel:''}</small></span>`;
  }).join('')}</div>`;
}
function tableHistory(g,summary,replay=false){
  const wide=replay&&globalThis.matchMedia?.('(min-width: 1000px) and (min-height: 540px)').matches;
  return `<details class="table-archive" data-table-panel="history" ${wide?'open':''}><summary>牌桌动态</summary><div class="table-log"><div class="match-meta">${summary}</div><div class="log-entries">${g.log.map(text=>`<div class="log-entry">${esc(text)}</div>`).join('')}</div><button class="text-button" data-action="rules">玩法手册</button></div></details>`;
}
function visibleCard(c){
  const changed=c.effective!==undefined&&c.effective!==c.rank;
  return `<span class="${['H','D'].includes(c.suit)||c.rank===17?'red':''}">${ranks[c.rank]}${suits[c.suit]||''}${changed?'→'+ranks[c.effective]:''}</span>`;
}
function seatRevealedHand(r,g,seat){
  if(g.phase==='over')return '';
  const hands=(g.publicHands||[]).filter(h=>h.owner===seat);
  if(!hands.length)return '';
  const name=esc(r.players[seat].name),id=(r.replay?'replay':'table')+'-revealed-'+seat;
  const cards=hands.flatMap(h=>h.cards);
  return `<button class="seat-reveal" data-reveal-hand="${id}" aria-haspopup="dialog" aria-label="查看${name}的全部明牌"><small>明牌</small><span class="reveal-strip">${cards.slice(0,12).map(visibleCard).join('')}</span><b>${cards.length>12?'…':'›'}</b></button>
    <dialog class="reveal-sheet" id="${id}" aria-label="${name}的明牌"><header><strong>${name} · 明牌</strong><button class="icon-button" data-close-revealed aria-label="关闭明牌">×</button></header>
    ${hands.map((h,i)=>`<div>${hands.length>1?'手牌 '+(i?'B':'A')+' · ':''}${h.cards.length} 张<div class="public-hand-cards">${h.cards.map(visibleCard).join('')}</div></div>`).join('')}</dialog>`;
}
function publicHandsPanel(r,g){
  const hands=g.publicHands||[];
  if(!r.spectator||g.phase==='over'||!hands.length)return '';
  return `<details class="public-hands spectator-hands" data-table-panel="public" open><summary>全员手牌</summary><div class="public-hand-grid">${hands.map(h=>`<section><strong>${esc(r.players[h.owner].name)}${hands.filter(other=>other.owner===h.owner).length>1?' · '+(hands.find(other=>other.owner===h.owner)===h?'A':'B'):''} <small>${h.cards.length} 张</small></strong><div class="public-hand-cards">${h.cards.map(visibleCard).join('')}</div></section>`).join('')}</div></details>`;
}
function showAuth(tab='login') {
  authTab=tab;
  showModal('auth',`<h2 class="modal-title">${tab==='login'?'登录':'注册'}</h2><div class="switch-tabs"><button data-action="auth-login" class="${tab==='login'?'active':''}">登录</button><button data-action="auth-register" class="${tab==='register'?'active':''}">注册</button></div><form class="form" id="auth-form"><label>玩家昵称<input name="name" required minlength="2" maxlength="18" autocomplete="username" placeholder="你的牌桌名字"></label><label>密码<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="${tab==='login'?'current-password':'new-password'}" placeholder="至少 8 个字符"></label><p class="form-error"></p><button class="primary full" type="submit">${tab==='login'?'登录':'注册'} →</button><p class="form-note">${tab==='register'?'初始 1000 积分。':''}</p></form>`,'WELCOME TO THE CLUB');
}
function showCreate(mode='landlord') {
  createMode=mode;
  const single=screen==='single',capacity=mode==='landlord'||mode==='trio'?3:4,pref=state.preferences||{};
  const advanced=['standard','trio','conveyor'].includes(mode);
  const options=`${advanced?'<label class="checkbox"><input type="checkbox" name="disableAdvancedHui">不启用回进阶版</label><label class="checkbox"><input type="checkbox" name="disableAdvancedDead">不启用死压进阶版</label>':''}${['basic','standard'].includes(mode)?'<label class="checkbox"><input type="checkbox" name="tribute">启用进贡</label>':''}${mode==='conveyor'?conveyorCreateOptions():''}${mode==='standard'?'<label class="checkbox"><input type="checkbox" name="dlc">Fieldlark 三周年 DLC（额外 40 张）</label>':''}`;
  showModal('create',`<h2 class="modal-title">${esc(names[mode])}</h2><form class="form" id="create-form"><fieldset class="ai-invitation"><legend>${single?'AI 对手':'邀请 AI'}</legend>${single?`<p class="form-note">${capacity-1} 位 AI</p>`:`<label>邀请人数<select name="botCount">${Array.from({length:capacity},(_,n)=>`<option value="${n}">${n===0?'不邀请':n+' 位 AI'}</option>`).join('')}</select></label>`}<label data-ai-type ${single?'':'hidden'}>AI 类型<select name="aiType"><option value="rules">规则 AI</option><option value="model" ${pref.configured?'':'disabled'}>模型 AI ${pref.configured?'· '+esc(pref.model):'· 需配置 API'}</option></select></label></fieldset>${!single?'<fieldset class="room-access"><legend>房间权限</legend><label>加入方式<select name="joinPolicy"><option value="code">仅房间号加入</option><option value="match">允许匹配加入</option></select></label><label class="checkbox"><input type="checkbox" name="allowSpectators">允许观战（可查看手牌）</label></fieldset>':''}${options?`<details class="room-options"><summary>规则选项${advanced?' · 默认开启进阶规则':''}</summary><div>${options}</div></details>`:''}<div class="create-submit"><p class="form-note">${single?'单人模式不计积分。':'全真人对局计分，含 AI 对局不计分。'}</p><p class="form-error" role="alert"></p><button class="primary full" type="submit">${single?'开始单人游戏':'创建房间'} →</button></div></form>`);
}

async function showLeaderboard(){requireUser(async()=>{showModal('leaderboard','<h2 class="modal-title">积分榜</h2><div class="empty">加载中…</div>','THE LEADERBOARD');try{const d=await api('leaderboard');if(modalKind!=='leaderboard')return;$('#modal-content').innerHTML='<h2 class="modal-title">积分榜</h2>'+d.players.map((p,i)=>`<div class="leader-row"><span class="place">${String(i+1).padStart(2,'0')}</span><div>${esc(p.name)}${p.id===state.user.id?' · 你':''}<small>${p.rank} / ${p.wins} 胜 ${p.games} 场</small></div><span class="points">${p.points}</span></div>`).join('');}catch(e){toast(e.message);}});}
async function showProfile(){requireUser(async()=>{const u=state.user;showModal('profile',`<h2 class="modal-title">${esc(u.name)}</h2><p class="modal-desc">${u.rank}</p><div class="profile-stats"><div><strong>${u.points}</strong><small>当前积分</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div id="history"><p class="empty">正在加载战绩…</p></div><div class="divider"></div><button class="secondary full" data-action="logout">退出账号</button>`,'PLAYER ARCHIVE');try{const d=await api('history');if(modalKind!=='profile')return;$('#history').innerHTML=d.history.length?''+d.history.map(h=>`<div class="leader-row"><span>${h.delta>0?'胜':'负'}</span><div>${names[h.mode]}<small>${new Date(h.created*1000).toLocaleString('zh-CN')}</small></div><span class="points">${h.delta>0?'+':''}${h.delta}</span></div>`).join(''):'<p class="empty">暂无真人战绩。</p>';}catch(e){toast(e.message);}});}
function showRules(){
 if(state.room?.mode==='conveyor'){conveyorRules();return;}
 showModal('rules',`<h2 class="modal-title">玩法手册</h2><div class="switch-tabs"><button class="active" data-action="rules-classic">斗地主</button><button data-action="rules-special">4A4A4 2.4</button></div><div id="rule-text" class="rules"></div>`,'THE RULEBOOK');ruleText('classic');
}
function ruleText(type){
 $$('.switch-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.action==='rules-'+type));
 $('#rule-text').innerHTML=type==='classic'?`<h3>三人 · 一副牌</h3><p>每人 17 张，余下 3 张归地主。轮流叫 1–3 分，只能叫更高的分；叫 3 分立即成为地主。全部不叫时，本实现将最后叫分玩家设为 1 分地主。</p><h3>常见牌型</h3><p>单张、对子、三张、三带一、三带一对、顺子（至少 5 张，不含 2 和王）、连对（至少 3 对）、飞机及带单/带对、四带二、四带两对。飞机的翅膀不能包含机身点数；单翼允许同点。</p><p>相同牌型、相同张数比大小。四张同点炸弹压普通牌；一小王加一大王为最大王炸。点数 3 最小，2 大于 A，大王最大。</p><h3>胜负与积分</h3><p>地主先出完则地主胜，任一农民先出完则两位农民胜。全真人牌桌胜方每人 +24，负方每人 −24，最低 0；有 AI 不结算积分。</p>`:`<h3>标准版与变体</h3><p>标准版四人 110 张：两副牌和两张急牌。对座组队，主牌初始为 3，点数大于 2、小于小王。主牌可按原点数组成顺子、连对和飞机；2 和王不参与连续牌型。</p><p>三人 86 张：去掉两副牌的黑桃 3–K、两张小王和一张急牌，加入一张大王；每人独立争先。基础版四人 54 张：一副牌，三张起炸，顺子至少三张、连对至少两对，不允许任何带牌组合，仅额外支持勾、叉、4A4，同样亮黑桃 3 定先手，不使用升变。</p><p>Fieldlark DLC 额外加入黑桃 A ×5、Delta A ×2、Delta 2–K 各2张、大小王各1张、急牌×7，共额外40张。可在创建标准房间时选择。</p><h3>开局</h3><p>可展示至少六张原生同点牌进行升变，多人升变取自然点数最大的牌为主。全桌共用 10 秒亮牌和升变，倒计时结束自动继续。多人亮黑桃 3 时用猜拳决定先手，每轮共用 10 秒，可同时出拳。无人亮牌时随机选先手。下一局由上一局最先出完者先发牌、先出牌。</p><h3>带牌</h3><p>标准版与三人版：N 张同点牌可带 1 至 N−2 个单位（N 至少为 3）。单位按单牌或对子计数；单牌附件按实际张数计算，允许混合单牌、对子及更多同点牌。例如五带三可带一单加一对，六带四可带两单加一对或一单加三张同点牌；全部对子也可按张数跟单牌附件。附件不能与主组同点。连续两组及以上同样张数的主体也可组成飞机：每组四张可带一或两个单位，每组五张可带一至三个单位，以此类推；各组带牌单位数及类型一致。相同主组张数、附件单位数与单位类型才可比大小。基础版不允许带牌。</p><h3>特殊出牌</h3><table><tr><th>出法</th><th>条件与效果</th></tr><tr><td>叉</td><td>两张同点，管同点单张；叉后只能勾，无人勾则叉牌者继续出牌。</td></tr><tr><td>勾</td><td>一张同点，管叉出的两张牌；勾后可用同点对子再叉，再用同点单牌勾；无人再叉则勾牌者自由出牌。</td></tr><tr><td>点</td><td>一张同点，管非勾叉对子。</td></tr><tr><td>死点</td><td>用同点单张点对 2 或对主牌，取得自由牌权。传送带中，死点者先抽牌，其余玩家自动不出并抽牌，然后由死点者领出。</td></tr><tr><td>压</td><td>普通点之后按出牌顺序响应。轮到自己时，可用一张 2、主牌或王压点，取得自由牌权。</td></tr><tr><td>死压</td><td>三张同点，管非勾叉对子，直接获牌权。进阶版可用四张同点截获死压牌权。</td></tr><tr><td>回</td><td>同花色单牌管小于 2 的非特殊单牌，每轮一次。进阶版要求相同牌型、张数，主体各点数组的花色构成逐组相同，带牌附件任意；不比较点数。王、2 和主不能作为回牌或被回牌的主体，附件只需符合带牌规则。</td></tr><tr><td>黑桃 A</td><td>可以作为普通 A 单出；组合中可代替 3 到 2 的普通牌，不能代替王或急牌。可自动配牌或手动指定替代点数和花色。</td></tr><tr><td>急牌</td><td>选一张急牌和一张非急牌，在自己的出牌回合赠给任一仍在场玩家，公开显示赠送牌的花色与点数；急牌弃掉，不占出牌次数，可继续正常出牌或使用急牌。仅剩一张急牌自动末名。</td></tr></table><h3>炸弹与 4A4A4</h3><p>四炸 &lt; 双王 &lt; 五炸 &lt; 六炸 &lt; 三王 &lt; 七炸 &lt; 八炸 &lt; 四王 &lt; 九炸 &lt; 十炸 &lt; 基础 4A4A4 &lt; 更大 4A4A4。炸弹压普通及点牌；叉只能用勾管，勾可以再叉再勾。更多同点炸弹继续按张数排列。</p><p>标准 4A4A4 至少三张 4 和两张 A，4 的数量必须多于 A；等级只计算能配齐的组合：至少三张 4、两张 A，使用全部 A 和比 A 多一张的 4 计级；额外的 4 可以一起出，但不升级，例如 44444AA 与 444AA 同级。基础版最低两张 4 和一张 A。</p><h3>优先管牌</h3><p>叉、勾、点、死压可在优先窗口直接响应。联机限时五秒；窗口结束后，只能按当前桌面继续出牌。</p><h3>进贡</h3><p>创建房间时可勾选启用，默认关闭。启用后，下一局发牌后，被抓住的玩家交出最大普通牌（急牌不参与）。抓一人时首位出完者收贡；抓两人时胜方对家各选一张贡牌。收贡者分别还任意一张手牌给对应进贡者，完成后才能开局。</p><h3>胜负、主牌与爆牌</h3><p>其他在场玩家都不出时，牌权持有者可任意领出合法牌型。四人局已出完者的最后一手无人管牌时，牌权交给其仍在场的对家。四人局首位出完者所在队获胜，其对家出完后剩 1 人升 1 级、剩 2 人升 2 级、无人剩余不升级；败队不升级。两队各自从 3 升至 A，超过 A 停在 A；以 A 为主获胜后本轮结束，下一轮两队归零、主牌回 3 并重新亮黑桃 3。轮内后续对局不再亮黑桃 3，下一局使用胜队的主牌。三人第一位出完者胜，以个人累计胜局循环决定下一局主牌。</p><p>每人每局首次降至 10 张及以下时公布剩余张数，此后不再重复爆牌。“分”玩法停用。真人 4A4A4 胜方 +20、负方 −20，有 AI 不结算积分。多人对局返回大厅后由规则 AI 托管座位，对局继续；单人模式可随时结束本局。</p><h3>段位</h3><p>800 以下纸牌学徒，800–1099 墨线新秀，1100–1399 银笔高手，1400–1799 黑金大师，1800–2399 牌桌宗师，2400 起无冕传奇。</p>`;
}
function $$(s){return [...document.querySelectorAll(s)];}
async function gameAction(action,extra={}){
  const room=state.room;
  if(!room)return;
  const opening=room.game?.openingClock;
  const window=opening&&['reveal','promote','rps'].includes(action)?{matchId:room.matchId,openingPhase:room.game.phase,openingRound:opening.round}:{};
  return await mutation('action',{action,revision:room.revision,...window,...extra});
}
function wildRank(value){return typeof value==='object'?value?.rank:value;}
function wildcardPayload(){
  const cards=(state.room?.game?.hand||[]).filter(c=>selected.has(c.id));
  const wildIds=new Set(cards.filter(c=>c.rank===14&&(c.suit==='S'||state.room?.game?.conveyor?.skill==='wild')&&(!state.room?.game?.conveyor||conveyorDouble?.id!==c.id)).map(c=>c.id));
  if(!wildIds.size)return undefined;
  if(cards.every(c=>c.rank===14)&&(!state.room?.game?.conveyor||!conveyorDouble||!selected.has(conveyorDouble.id)))return undefined;
  const map=Object.fromEntries(Object.entries(wildcardMap).filter(([id,value])=>wildIds.has(id)&&wildRank(value)>=3&&wildRank(value)<=15));
  return Object.keys(map).length?map:undefined;
}
function urgentSelected(){
 return state.room.game.hand.some(c=>selected.has(c.id)&&(c.effective??c.rank)===18);
}
function selectedPlay(){
  const c=state.room.game.conveyor;
  const args={ids:[...selected]};
  const wild=wildcardPayload();
  if(wild!==undefined)args.wildcard=wild;
  if(c){
    args.actor=c.actor;
    if(conveyorDouble&&selected.has(conveyorDouble.id))args.double=conveyorDouble;
  }
  return args;
}
let previewKey='', previewTimer, previewText='';
function updateActionFeedback(r,g,canAct,canUrgent){
  const feedback=$('.action-feedback');
  if(!feedback)return;
  const clock=g.priorityClock;
  const ownsClock=clock?.seat===r.seat&&(!g.conveyor||clock.actor===g.conveyor.actor);
  const special=g.response?.moves?.[0]?.label;
  const yourTurn=g.turn===r.seat&&(!g.conveyor||g.conveyor.turnActor===g.conveyor.actor);
  const banned=!!g.conveyor?.resources?.ban;
  let turnLabel;
  if(ownsClock)turnLabel=(special?'可'+special:'优先管牌')+' · '+(clock.paused?'计时暂停':clock.remaining+' 秒');
  else if(clock)turnLabel=r.players[clock.seat].name+' · 优先管牌';
  else if(g.priorityResponder===r.seat)turnLabel='轮到你 · '+(special?'可'+special:'优先管牌')+'，可选择不出';
  else if(yourTurn)turnLabel=banned?'轮到你 · 禁手':g.conveyor?.mustScavenge?'轮到你 · 取牌并跳过':special?'轮到你 · 可'+special:g.last&&g.lastSeat!==(g.conveyor?.actor??r.seat)?'轮到你 · 跟牌':'轮到你 · 自由出牌';
  else if(special&&canAct)turnLabel='可'+special;
  else turnLabel=r.players[g.turn].name+' · 出牌中';
  const turn=$('[data-turn-label]',feedback);
  const turnText=turnLabel+(r.audioWaiting?' · 播报中，可先选牌':'');
  if(turn.textContent!==turnText)turn.textContent=turnText;
  feedback.classList.toggle('your-action',canAct&&!banned||!!canUrgent);

  const args=selected.size&&!banned&&!g.conveyor?.mustScavenge&&!canUrgent&&(canAct||r.audioWaiting)&&!urgentSelected()?selectedPlay():null;
  const key=args?JSON.stringify([tableKey(r),r.revision,args]):'';
  const output=$('[data-play-preview]',feedback);
  if(key!==previewKey){
    clearTimeout(previewTimer);
    previewKey=key;
    previewText='';
    if(key)previewTimer=setTimeout(async()=>{
      try{
        const result=await api('play-preview',{...args,revision:r.revision});
        if(key!==previewKey||!state.room||tableKey(state.room)!==tableKey(r)||state.room.revision!==r.revision)return;
        previewText=result.stale?'':(result.kind||result.reason||'');
        const current=$('[data-play-preview]');
        if(current&&previewText)current.textContent=previewText;
      }catch{/* Older sessions and transient disconnects still allow ordinary submission. */}
    },100);
  }
  const summary=canUrgent?'急牌 · 选择效果':selected.size?previewText||(urgentSelected()?'急牌 · 赠牌':selected.size+' 张已选'):'';
  if(output.textContent!==summary)output.textContent=summary;
}
function showWildcard(){
  const fresh=state.room?.game?.hand.filter(c=>selected.has(c.id))||[];
  const wild=fresh.filter(c=>c.rank===14&&(c.suit==='S'||state.room?.game?.conveyor?.skill==='wild')&&(!state.room?.game?.conveyor||c.id!==conveyorDouble?.id));
  if(fresh.length>1&&fresh.every(card=>card.rank===14)&&!(state.room?.mode==='conveyor'&&conveyorDouble&&selected.has(conveyorDouble.id))){toast('全是 A 时按原点数和花色出牌。');return;}
  const conveyor=state.room?.mode==='conveyor', label=state.room?.game?.conveyor?.skill==='wild'?'A':'黑桃 A';
  if(!wild.length||selected.size===1){toast('单张 A 按原点数和花色出牌；配牌请再选一张。');return;}
  if(conveyor){
    const options=wild.map((c,i)=>{
      const declared=wildcardMap[c.id];
      const points=wildRanks().map(n=>[n,ranks[n]]);
      const rankOptions=skillOptions('rank:'+c.id,'第 '+(i+1)+' 张 '+ranks[c.rank]+suits[c.suit]+' 的点数',points,{value:wildRank(declared)??14});
      const suitPicker=skillOptions('suit:'+c.id,'花色',suitOptions(),{className:'skill-suit-options',value:declared?.suit??c.suit});
      return `<section class="skill-card-pair">${rankOptions}${suitPicker}</section>`;
    }).join('');
    showModal('wildcard',`<h2 class="modal-title">${label} 配牌</h2><form class="form" id="wildcard-form">${options}<button class="primary full" type="submit">确认配牌</button></form>`);
    return;
  }
  showModal('wildcard',`<h2 class="modal-title">${label} 配牌</h2><p class="modal-desc">每张${label}可以独立代替非王牌。选择 A 表示保留原点数。</p><form class="form" id="wildcard-form">${wild.map((c,i)=>`<label>第 ${i+1} 张${label}<select name="rank:${esc(c.id)}">${wildRanks().map(n=>`<option value="${n}" ${n===(wildRank(wildcardMap[c.id])||14)?'selected':''}>${ranks[n]}</option>`).join('')}</select><select name="suit:${esc(c.id)}" aria-label="替代花色">${Object.entries(suits).filter(([s])=>['S','H','C','D'].includes(s)||s==='T'&&state.room.options.dlc).map(([s,label])=>`<option value="${s}" ${s===(wildcardMap[c.id]?.suit||c.suit)?'selected':''}>${label}</option>`).join('')}</select></label>`).join('')}<button class="primary full" type="submit">确认配牌 →</button></form>`,'WILDCARD DECLARATION');
}
function selectionUpdate(){
 if(state.room?.mode==='conveyor')conveyorAfterRender();
 $$('.hand .card').forEach(b=>{b.classList.toggle('selected',selected.has(b.dataset.card));b.setAttribute('aria-pressed',selected.has(b.dataset.card));});
 const returned=$('[data-action="tribute-return"]');if(returned)returned.disabled=selected.size!==1||state.room.audioWaiting;
 const g=state.room.game,r=state.room,canAct=(!g.priorityClock||g.priorityClock.seat===r.seat&&(!g.conveyor||g.priorityClock.actor===g.conveyor.actor))&&(!!g.response||g.turn===r.seat&&(!g.conveyor||g.conveyor.turnActor===g.conveyor.actor));
 const pass=$('[data-action="pass"]');if(pass)pass.disabled=!!r.audioWaiting||r.players[r.seat].autoplay||!canAct||!g.response&&((!g.last||g.lastSeat===(g.conveyor?g.conveyor.actor:r.seat))&&!g.conveyor?.resources?.ban);
 const canUrgent=g.conveyor&&!g.conveyor.waiting&&!g.conveyor.resources?.ban&&urgentSelected();
 const btn=$('[data-action="play"]');if(btn)btn.disabled=(!canUrgent&&(!canAct||g.conveyor?.directPending&&!g.response||!!g.conveyor?.resources?.ban||g.conveyor?.mustScavenge||!!g.priority&&r.players.filter(p=>!p.bot).length===1&&!g.priority.pending.includes(r.seat)))||r.audioWaiting||r.players[r.seat].autoplay||!selected.size;
 const hint=$('[data-action="hint"]');if(hint)hint.disabled=!!g.conveyor?.mustScavenge;
 const wildcardButton=$('[data-action="declare-wild"]');
 if(wildcardButton){
   const hasOther=g.hand.some(c=>selected.has(c.id)&&(c.rank!==14||g.conveyor&&c.id===conveyorDouble?.id));
   wildcardButton.hidden=!hasOther||!g.hand.some(c=>selected.has(c.id)&&c.rank===14&&(c.suit==='S'||g.conveyor?.skill==='wild')&&(!g.conveyor||c.id!==conveyorDouble?.id));
   const declared=wildcardPayload();
   for(const card of $$('.hand [data-card]')){
     const match=g.hand.find(c=>c.id===card.dataset.card&&c.rank===14&&(c.suit==='S'||g.conveyor?.skill==='wild'));
     const change=match&&selected.has(match.id)?(typeof declared==='object'?declared[match.id]:declared):null;
     if(change)card.dataset.declaration='→'+ranks[wildRank(change)]+(suits[change.suit]||'');
     else delete card.dataset.declaration;
   }
 }
 const splitButton=$('[data-action="cv-double"]');
 if(g.conveyor?.skill==='double'){
   for(const card of $$('.hand [data-card]')){
     delete card.dataset.splitDeclaration;
     if(card.dataset.card===conveyorDouble?.id&&selected.has(conveyorDouble.id)){
       card.dataset.splitDeclaration='→ '+conveyorDouble.ranks.map((rank,i)=>ranks[rank]+suits[conveyorDouble.suits[i]]).join(' ');
     }
   }
 }
 if(splitButton)splitButton.hidden=!g.hand.some(c=>selected.has(c.id)&&[13,14,15,g.main].includes(c.rank));
 if($('.action-feedback'))updateActionFeedback(r,g,canAct,canUrgent);
}
let cardSweep=null, suppressCardClick=false, renderAfterSweep=false;
function sweepCard(card){
 if(!card||!cardSweep||cardSweep.visited.has(card.dataset.card))return;
 cardSweep.visited.add(card.dataset.card);
 cardSweep.selecting?selected.add(card.dataset.card):selected.delete(card.dataset.card);
}
document.addEventListener('pointerdown',e=>{
 if(e.isPrimary===false||cardSweep&&e.pointerId!==cardSweep.pointerId)return;
 cardSweep=null;suppressCardClick=false;
 if(!['mouse','touch','pen'].includes(e.pointerType)||e.button!==0)return;
 const card=e.target.closest('.hand [data-card]');if(!card)return;
 cardSweep={pointerId:e.pointerId,selecting:!selected.has(card.dataset.card),visited:new Set(),x:e.clientX,y:e.clientY};
 suppressCardClick=true;card.setPointerCapture?.(e.pointerId);sweepCard(card);selectionUpdate();e.preventDefault();
});
document.addEventListener('pointermove',e=>{
 if(!cardSweep||e.pointerId!==cardSweep.pointerId||e.pointerType==='mouse'&&!(e.buttons&1))return;
 const {x,y}=cardSweep, steps=Math.max(1,Math.ceil(Math.hypot(e.clientX-x,e.clientY-y)/8));
 for(let i=1;i<=steps;i++)sweepCard(document.elementFromPoint(x+(e.clientX-x)*i/steps,y+(e.clientY-y)*i/steps)?.closest('.hand [data-card]'));
 cardSweep.x=e.clientX;cardSweep.y=e.clientY;selectionUpdate();e.preventDefault();
});
function endCardSweep(e){
 if(e.pointerId!==cardSweep?.pointerId)return;
 cardSweep=null;
 if(e.type==='pointercancel')suppressCardClick=false;
 if(renderAfterSweep){renderAfterSweep=false;render();}
}
document.addEventListener('pointerup',endCardSweep);
document.addEventListener('pointercancel',endCardSweep);
document.addEventListener('click',async e=>{
 const c=e.target.closest('[data-card]');if(c){if(suppressCardClick&&(e.detail||['touch','pen'].includes(e.pointerType))){suppressCardClick=false;return;}selected.has(c.dataset.card)?selected.delete(c.dataset.card):selected.add(c.dataset.card);selectionUpdate();return;}
 const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
 const action=b.dataset.action;
 try{
 switch(action){
 case 'preview-effect':gameAudio.effect('play');break;
 case 'preview-voice':gameAudio.speak('三带一对');break;
 case 'close':closeModal();break;
 case 'auth':showAuth();break;
 case 'auth-login':showAuth('login');break;
 case 'auth-register':showAuth('register');break;
 case 'open-create':navigate('create');if(!state.user)showAuth();break;
 case 'open-single':navigate('single');if(!state.user)showAuth();break;
 case 'choose-mode':requireUser(()=>showCreate(b.dataset.mode));break;
 case 'home':if(state.room){toast('请先离开当前房间再返回主菜单。');break;}closeModal();navigate('home');break;
 case 'checkin':{
   const result=await mutation('checkin');
   if(result)toast('签到获得 '+result.checkin.reward+' 积分，已连续 '+result.checkin.streak+' 天。');
   break;
 }
 case 'settings':case 'settings-api':settingsTab=action==='settings-api'?'api':'account';if(state.room)showSettingsModal();else navigate('settings');break;
 case 'settings-tab':settingsTab=b.dataset.tab;if(state.room)showSettingsModal();else{renderedKey='';render();}break;
 case 'lobby':if(state.room)toast('当前仍在房间中。请离开房间后返回主菜单。');else {closeModal();navigate('home');}break;
 case 'seat-profile':await openPlayerProfile(state.room,Number(b.dataset.playerSeat));break;
 case 'table-tools':showModal('table-tools',`<h2 class="modal-title">牌桌操作</h2><div class="table-tool-list">${showHandButton(state.room,state.room.game)}<button class="secondary" data-action="rules">玩法手册</button><button class="secondary" data-action="settings">设置</button></div>`);break;
 case 'autoplay':if(await mutation('autoplay',{enabled:!state.room.players[state.room.seat].autoplay})){selected.clear();wildcardMap={};renderedKey='';render();}break;
 case 'match':requireUser(async()=>{await mutation('match',{mode:b.dataset.mode});});break;
 case 'watch':{const input=$('#join-code');if(input.reportValidity())requireUser(async()=>{await mutation('watch',{code:input.value});});break;}
 case 'show-hand':if(await mutation('show-hand',{})&&modalKind==='table-tools')closeModal();break;
 case 'chat-menu':showModal('chat',`<h2 class="modal-title">发言</h2><div class="chat-choices">${(state.features?.chatPhrases||[]).map(text=>`<button class="secondary" data-action="chat-send" data-text="${esc(text)}">${esc(text)}</button>`).join('')}</div>`);break;
 case 'chat-send':if(await mutation('chat',{text:b.dataset.text}))closeModal();break;
 case 'rules':showRules();break;
 case 'rules-classic':ruleText('classic');break;
 case 'rules-special':ruleText('special');break;
 case 'leaderboard':showLeaderboard();break;
 case 'profile':showProfile();break;
 case 'logout':await mutation('logout');closeModal();navigate('home');break;
 case 'copy':try{await navigator.clipboard.writeText(state.room.code);toast('房间号已复制：'+state.room.code);}catch{toast('房间号：'+state.room.code);}break;
 case 'invite-ai':showModal('invite-ai',`<h2 class="modal-title">邀请 AI</h2><div class="gift-players"><button class="secondary" data-action="bot">规则 AI</button><button class="secondary" data-action="model-bot" ${state.preferences?.configured?'':'disabled'}>模型 AI ${state.preferences?.configured?'':'· 需配置 API'}</button><button class="text-button" data-action="settings-api">API 设置 ↗</button></div>`);break;
 case 'bot':if(await mutation('bot')){if(modalKind==='invite-ai')closeModal();}break;
 case 'remove':await mutation('remove',{seat:Number(b.dataset.seat)});break;
 case 'model-bot':if(await mutation('bot',{model:true})){if(modalKind==='invite-ai')closeModal();}break;
 case 'clear-api':await mutation('model-settings',{clear:true});if(state.room)showSettingsModal();else{renderedKey='';render();}toast('API 配置已清除。');break;
 case 'start':selected.clear();await mutation('start');break;
 case 'leave':await mutation('leave');break;
 case 'resign':showModal('resign',`<h2 class="modal-title">${state.room.single?'结束这一局？':'返回大厅？'}</h2><p class="modal-desc">${state.room.single?'本局将立即结束。':'离开后由规则 AI 托管你的座位，对局继续。'}</p><div class="phase-actions"><button class="secondary" data-action="close">继续打牌</button><button class="primary" data-action="resign-confirm">${state.room.single?'结束本局':'返回大厅'}</button></div>`);break;
 case 'resign-confirm':await mutation('resign');closeModal();break;
 case 'tribute-pick':await gameAction('tribute-pick',{target:Number(b.dataset.seat)});break;
 case 'tribute-return':if(await gameAction('tribute-return',{ids:[...selected]})){selected.clear();renderedKey='';render();}break;
 case 'bid':await gameAction('bid',{value:Number(b.dataset.value)});break;
 case 'pass':await gameAction('pass',state.room.mode==='conveyor'?{actor:state.room.game.conveyor.actor}:{});break;
 case 'reveal':case 'confirm':await gameAction(action);break;
 case 'promote':await gameAction('promote',{rank:Number(b.dataset.rank)});break;
 case 'rps':await gameAction('rps',{value:b.dataset.value});break;
 case 'declare-wild':showWildcard();break;
 case 'deselect':selected.clear();selectionUpdate();break;
 case 'hint':{
   const hintRoom=state.room?.code,hintMatch=state.room?.matchId;
   const result=await api('hint',{});if(state.room?.code!==hintRoom||state.room?.matchId!==hintMatch||state.room?.game?.phase!=='play'||state.room.game.finished.includes(state.room.seat))return;hintMoves=result.moves;if(!hintMoves.length){toast(result.reason||'未找到提示方案，可手动选牌或选择不出。');return;}
   const move=hintMoves[hintIndex++%hintMoves.length];if(state.room.mode==='conveyor')conveyorDouble=move.double||null;selected=new Set(move.ids);wildcardMap=move.wildcard||{};renderedKey='';render();break;
 }
 case 'gift-player':{
   const args={ids:[...selected],target:Number(b.dataset.seat)};
   const result=await gameAction('urgent',args);if(result){closeModal();wildcardMap={};renderedKey='';render();toast('赠牌完成，不占出牌次数，可以继续出牌。');}break;
 }
 case 'play':{
   if(state.room.mode==='conveyor'){await conveyorPlay();break;}
   if(urgentSelected()){if(state.room.game.turn!==state.room.seat){toast('请在自己的出牌回合使用急牌。');return;}showModal('gift',`<h2 class="modal-title">赠送给谁？</h2><p class="modal-desc">选中的急牌将弃掉，另一张牌交给你选择的玩家。赠牌不占出牌次数。</p><div class="gift-players">${state.room.players.map((p,s)=>s!==state.room.seat&&!state.room.game.finished.includes(s)?`<button class="secondary" data-action="gift-player" data-seat="${s}">${esc(p.name)} <small>${state.room.game.counts[s]} 张手牌</small></button>`:'').join('')}</div>`,'URGENT GIFT');break;}
   await gameAction('auto',selectedPlay());break;
 }
 }
 }catch(error){toast(error.message);}
});
function openRevealedHand(sheet){
 if(!sheet)return;
 if(!sheet.open)sheet.showModal();
 const anchor=sheet.previousElementSibling.getBoundingClientRect();
 const width=sheet.offsetWidth,height=sheet.offsetHeight;
 const left=Math.min(Math.max(8,anchor.left),window.innerWidth-width-8);
 const top=anchor.bottom+height+12<=window.innerHeight?anchor.bottom+4:Math.max(8,anchor.top-height-4);
 sheet.style.left=left+'px';sheet.style.top=top+'px';
}
window.addEventListener('resize',()=>openRevealedHand($('.reveal-sheet[open]')));
// Replay handles ordinary table clicks inside its own dialog.
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-reveal-hand],[data-close-revealed]');
 if(!button)return;
 if(button.hasAttribute('data-close-revealed'))button.closest('dialog').close();
 else openRevealedHand(document.getElementById(button.dataset.revealHand));
},true);
document.addEventListener('input',e=>{const key=e.target.dataset.volume;if(key){gameAudio.setVolume(key,e.target.value/100);$('#volume-'+key).textContent=e.target.value+'%';}});
document.addEventListener('keydown',e=>{
 if(e.repeat||modal.open||$('#seat-profile')?.open||(e.key==='Enter'&&e.target.closest('button[data-player-seat]'))||$('.reveal-sheet[open]')||(e.key==='Enter'&&e.target.closest('[data-reveal-hand]'))||$('#playtest-replay-dialog')?.open||e.target.closest('input,textarea,select,[contenteditable="true"]'))return;
 const action=e.key==='Enter'?(state.room?.game?.phase==='tribute'?'tribute-return':'play'):e.key==='Escape'?'deselect':null;
 if(!action)return;const button=$(`[data-action="${action}"]`);
 if(button&&!button.disabled){e.preventDefault();button.click();}
});
document.addEventListener('change',e=>{
 if(e.target.matches('[data-party-mode]')){
  partyMode=e.target.checked;
  try {localStorage.setItem('vgc-party-mode',partyMode?'1':'0');} catch {}
  if(!partyMode)partyBurst?.remove();
 }
 if(e.target.name==='botCount'){const field=$('[data-ai-type]',e.target.form);if(field)field.hidden=e.target.value==='0';}
});
document.addEventListener('submit',async e=>{
 if(e.target.method==='dialog')return;
 e.preventDefault();const f=e.target;
 if(f.id==='join-form'){const code=$('#join-code').value;requireUser(async()=>{await mutation('join',{code,...(screen==='single'?{single:true}:{})});});return;}
 const error=$('.form-error',f);const submit=$('button[type=submit]',f);if(submit)submit.disabled=true;
 try{
 if(f.id==='wildcard-form'){const data=new FormData(f);wildcardMap=Object.fromEntries([...data].filter(([name])=>name.startsWith('rank:')).map(([name,v])=>{const id=name.slice(5);return [id,{rank:Number(v),suit:data.get('suit:'+id)}];}));closeModal();renderedKey='';render();}
 if(f.id==='auth-form'){const data=Object.fromEntries(new FormData(f));await api(authTab,data);closeModal();renderedKey='';await sync();if(!state.room)toast(authTab==='login'?'欢迎回到VGC。':'注册成功，牌桌在等你。');}
 if(f.id==='create-form'){await api('create',{mode:createMode,single:screen==='single',options:{allowMatching:f.elements.joinPolicy?.value==='match',allowSpectators:f.elements.allowSpectators?.checked||false,advancedHui:['standard','trio','conveyor'].includes(createMode)&&!f.elements.disableAdvancedHui?.checked,advancedDead:['standard','trio','conveyor'].includes(createMode)&&!f.elements.disableAdvancedDead?.checked,dlc:f.elements.dlc?.checked||false,tribute:f.elements.tribute?.checked||false,...(createMode==='conveyor'?conveyorFormOptions(f):{})}});const count=screen==='single'?(createMode==='landlord'||createMode==='trio'?2:3):Number(f.elements.botCount.value);for(let i=0;i<count;i++)await api('bot',{model:f.elements.aiType.value==='model'});if(screen==='single'&&createMode!=='conveyor')await api('start',{});closeModal();await sync();}
 if(f.id==='api-settings-form'){await api('model-settings',Object.fromEntries(new FormData(f)));f.reset();await sync();if(state.room)showSettingsModal();toast('模型 API 已保存。');}
 if(f.id==='account-form'){await api('account',Object.fromEntries(new FormData(f)));f.elements.currentPassword.value='';f.elements.newPassword.value='';await sync();if(state.room)showSettingsModal();toast('账号信息已更新。');}
 }catch(e){if(error)error.textContent=e.message;else toast(e.message);}finally{if(submit)submit.disabled=false;}
});
modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
modal.addEventListener('close',()=>{modalKind='';});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){clearTimeout(pollTimer);poll();}});
render();poll();
