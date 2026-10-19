'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {landlord:'斗地主',standard:'4A4A4',trio:'4A4A4 · 三人',basic:'4A4 · 基础'};
const ranks = {3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'10',11:'J',12:'Q',13:'K',14:'A',15:'2',16:'小王',17:'大王',18:'急'};
const wildRanks = () => [...Array.from({length:13},(_,i)=>i+3), ...(state.features?.wildUrgent?[18]:[])];
const suits = {S:'♠',H:'♥',C:'♣',D:'♦',T:'Δ',J:'✦',U:'↗'};
let state = {user:null,room:null}, selected = new Set(), wildcard = '', wildcardMap = {}, hintIndex = 0, hintMoves = [], renderedKey = '', lastPhase = '', busy = false, authTab = 'login', createMode = 'landlord', modalKind = '';
let responseKey='', pollTimer, toastTimer, screen='home', settingsTab='account';
const modal = $('#modal');
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3500); }
async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {cache:'no-store',headers:{'X-Poker-Audio':document.hidden?'0':'1'}} : {method:'POST',headers:{'Content-Type':'application/json','X-Poker-Audio':document.hidden?'0':'1'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请重试。');
  return data;
}
function markResponse(){
 const r=state.room,g=r?.game,response=g?.response;
 const key=response?`${r.code}/${r.matchId}/${response.key}`:'';
 if(key===responseKey)return;
 if(responseKey){selected.clear();wildcard='';wildcardMap={};}
 responseKey=key;
 if(response?.moves.length){const move=response.moves[0];selected=new Set(move.ids);wildcard='';wildcardMap=move.wildcard||{};}
}
async function mutation(path, body = {}) {
  if (busy) return;
  busy = true;
  try { const result = await api(path,body); if ('room' in result) {state.room = result.room; markResponse(); renderedKey = ''; render();} await sync(); return result; }
  catch(e) {toast(e.message); await sync();}
  finally {busy = false;}
}
async function sync() {
  try {
    const next = await api('state');
    const oldRoom = state.room?.code, oldMatch = state.room?.matchId;
    state = next;
    if (oldRoom !== state.room?.code || oldMatch !== state.room?.matchId) {selected.clear(); wildcard='';wildcardMap={};}
    markResponse();
    const available = new Set(state.room?.game?.hand.map(c=>c.id) || []);
    selected = new Set([...selected].filter(id=>available.has(id)));
    render();
  } catch {}
}
async function poll() {await sync(); pollTimer = setTimeout(poll, document.hidden ? 2500 : 850);}
function showModal(kind, content) {modalKind=kind; $('#modal-content').innerHTML=content; if(!modal.open) modal.showModal();}
function closeModal() {modal.close(); modalKind='';}
function requireUser(fn) {if(!state.user) {showAuth();return;} fn();}
function card(c, interactive=false, g=null) {
  const red = c.suit==='H'||c.suit==='D'||c.rank===17;
  const wild = g && !['landlord','basic'].includes(g.mode) && c.suit==='S' && c.rank===14;
  const label = `${ranks[c.rank]}${suits[c.suit]}`;
  return `<${interactive?'button':'div'} class="card ${red?'red':''} ${c.rank>=16?'joker':''} ${selected.has(c.id)&&interactive?'selected':''} ${wild?'wild':''} ${g&&g.mode!=='landlord'&&c.rank===g.main?'main-card':''}" ${interactive?`data-card="${esc(c.id)}" aria-pressed="${selected.has(c.id)}" aria-label="${esc(label)}${wild?'，混子':''}"`:''}><span class="card-rank">${ranks[c.rank]}</span><span class="card-suit">${c.rank>=16?'':suits[c.suit]}</span><span class="card-center">${c.rank>=16?(c.rank===18?'↗':'✦'):suits[c.suit]}</span><span class="card-bottom">${label}</span></${interactive?'button':'div'}>`;
}
function render() {
  const u=state.user,r=state.room,g=r?.game;
  document.body.classList.toggle('home-screen',!r&&screen==='home');
  document.body.classList.toggle('in-game',!!g);
  gameAudio.observe(r);
  const key = JSON.stringify([u,r,screen,settingsTab,state.preferences]);
  if(key===renderedKey)return;
  renderedKey=key;
  const handScroll=$('.hand')?.scrollLeft||0;
  const joinInput=$('#join-code'); const joinValue=joinInput?.value; const joinFocus=document.activeElement===joinInput;
  if(!r) $('#view').innerHTML=screen==='home'?lobby():screen==='settings'?settingsScreen():flowScreen();
  else if(!g) $('#view').innerHTML=waiting(r);
  else $('#view').innerHTML=table(r,g);
  if(joinValue!==undefined && $('#join-code')){$('#join-code').value=joinValue; if(joinFocus)$('#join-code').focus();}
  if($('.hand'))$('.hand').scrollLeft=handScroll;
  if($('.log-entries'))$('.log-entries').scrollTop=$('.log-entries').scrollHeight;
  if(r?.audioWaiting){
    const actions=new Set(['start','play','pass','bid','reveal','confirm','promote','rps','tribute-pick','tribute-return','accept','reject','gift-player','resign-confirm']);
    $$('[data-action]').filter(b=>actions.has(b.dataset.action)).forEach(b=>b.disabled=true);
  }
  if(g && lastPhase!==g.phase){if(lastPhase==='rps'&&g.phase==='play')toast('猜拳获胜：'+r.players[g.turn].name+'，先出牌。');hintMoves=[];hintIndex=0;lastPhase=g.phase;}
  if(!g)lastPhase='';

}
function lobby() {
  const u=state.user;
  return `<section class="game-home"><div class="home-copy"><h1 class="home-title">VGC<span>扑克牌俱乐部</span></h1><div class="main-menu"><button class="main-menu-item" data-action="open-create"><span class="menu-label">创建房间</span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="open-single"><span class="menu-label">单人模式</span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="settings"><span class="menu-label">设置</span><span class="menu-arrow">↗</span></button></div><div class="home-bottom"><span>${u?esc(u.name)+' · '+esc(u.rank)+' / '+u.points+' 积分':''}</span><button class="text-button" data-action="${u?'leaderboard':'auth'}">${u?'积分榜':'登录 / 注册'} ↗</button></div></div><div class="home-scene" aria-hidden="true"><div class="sketch-ring ring-one"></div><div class="sketch-ring ring-two"></div><div class="home-card-fan">${[['4','♣'],['A','♥'],['4','♠'],['A','♦'],['4','♣']].map(([r,s],i)=>`<div class="home-art-card ${s==='♥'||s==='♦'?'red':''}" data-index="${i}"><span>${r}<small>${s}</small></span><b>${s}</b><i>${r}<small>${s}</small></i></div>`).join('')}</div></div></section>`;
}
function flowScreen(){
 const single=screen==='single';
 return `<div class="flow-heading"><button class="menu-back" data-action="home">← 返回主菜单</button><h1>${single?'单人模式':'创建房间'}</h1></div><div class="mode-layout"><section class="mode-grid">${[['landlord','01','经典斗地主','三人 / 54 张','叫分争地主，联手定胜负。','♠'],['standard','02','4A4A4 标准版','四人 / 110 张 / 2.4','勾叉点压，见招拆招。','4A'],['trio','03','4A4A4 三人版','三人 / 86 张','各自为战，争先出完。','♧'],['basic','04','4A4 基础版','四人 / 54 张','基础勾叉，三张起炸。','4']].map(([m,,t,n,,mark])=>`<button class="mode-card" data-action="choose-mode" data-mode="${m}"><span class="mode-symbol">${mark}</span><h2>${t}</h2><div class="mode-foot"><small>${n}</small><span>选择 →</span></div></button>`).join('')}</section><aside class="flow-aside">${single?`<div class="side-panel"><h3>AI 对手</h3><button class="text-button" data-action="settings-api">模型 API 设置 ↗</button><p>单人模式不计积分。</p><div class="divider"></div><h3>加入房间</h3><form id="join-form"><input id="join-code" class="join-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="— — —" aria-label="六位房间号" autocomplete="off"><button class="secondary full" type="submit">加入房间 →</button></form></div>`:`<div class="side-panel"><h3>加入房间</h3><form id="join-form"><input id="join-code" class="join-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="— — —" aria-label="六位房间号" autocomplete="off"><button class="secondary full" type="submit">加入房间 →</button></form><div class="divider"></div><p>仅全真人对局计分。</p></div>`}</aside></div>`;
}
function settingsScreen(){
 const u=state.user, pref=state.preferences||{};
 const tabs=[['account','账号信息'],['audio','声音'],['api','模型 API'],['archive','积分与战绩']];
 let content='';
 if(settingsTab==='audio')content=`<h2>声音</h2><div class="audio-controls">${[['effects','音效'],['music','音乐'],['voice','语音']].map(([key,label])=>`<label><span>${label}<output id="volume-${key}">${Math.round(gameAudio.volumes[key]*100)}%</output></span><input type="range" min="0" max="100" value="${Math.round(gameAudio.volumes[key]*100)}" data-volume="${key}" aria-label="${label}音量"></label>`).join('')}</div><div class="phase-actions"><button class="secondary" data-action="preview-effect">试听音效</button><button class="secondary" data-action="preview-voice">试听语音</button></div>`;
 else if(!u)content='<h2>请先登录</h2><p class="modal-desc">登录后管理账号、保存模型 API 和查看战绩。</p><button class="primary" data-action="auth">登录 / 注册 →</button>';
 else if(settingsTab==='account')content=`<h2>账号信息</h2><p class="modal-desc">${esc(u.rank)} · ${u.points} 积分 · ${u.games} 场真人对局</p><form class="form" id="account-form"><label>玩家昵称<input name="name" value="${esc(u.name)}" required minlength="2" maxlength="18" autocomplete="username"></label><label>当前密码<input name="currentPassword" type="password" required autocomplete="current-password" placeholder="保存信息时验证身份"></label><label>新密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空表示保留当前密码"></label><p class="form-note">修改密码后，其他设备的登录会话将退出。</p><p class="form-error"></p><button class="primary" type="submit">保存账号信息 →</button></form><div class="divider"></div><button class="text-button" data-action="logout">退出账号 ↗</button>`;
 else if(settingsTab==='api')content=`<h2>模型 API</h2><p class="modal-desc">${pref.configured?'已配置 · 密钥已保存到本次服务的内存中':'兼容 Chat Completions 的 HTTPS API。'}</p><form class="form" id="api-settings-form"><label>API 基础地址<input name="endpoint" type="url" required value="${esc(pref.endpoint||'')}" placeholder="https://api.example.com/v1"></label><label>模型名称<input name="model" required maxlength="100" value="${esc(pref.model||'')}" placeholder="模型 ID"></label><label>API 密钥<input name="key" type="password" ${pref.configured?'':'required'} autocomplete="off" placeholder="${pref.configured?'密钥已保存；留空表示不更换':'输入你的 API Key'}"></label><p class="form-note">模型只看到自己的手牌与公开局面。无效回答或请求失败时使用规则 AI。密钥不会返回浏览器或写入数据库，服务重启后需要重新配置。模型提供商可能按请求收费。</p><p class="form-error"></p><button class="primary" type="submit">保存模型配置 →</button></form>${pref.configured?'<div class="divider"></div><button class="text-button" data-action="clear-api">清除 API 配置 ↗</button>':''}`;
 else content=`<h2>积分与战绩</h2><p class="modal-desc">仅全真人对局计分。</p><div class="profile-stats"><div><strong>${u.points}</strong><small>${u.rank}</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div class="phase-actions"><button class="secondary" data-action="profile">最近战绩 →</button><button class="secondary" data-action="leaderboard">查看积分榜 →</button></div>`;
 return `<div class="flow-heading"><button class="menu-back" data-action="home">← 返回主菜单</button><h1>设置</h1></div><div class="settings-layout"><nav class="settings-tabs">${tabs.map(([k,t])=>`<button class="${settingsTab===k?'active':''}" data-action="settings-tab" data-tab="${k}">${t}<span>→</span></button>`).join('')}<div class="divider"></div><button data-action="rules">玩法手册 <span>↗</span></button></nav><section class="settings-content">${content}</section></div>`;
}
function showSettingsModal(){showModal('settings',settingsScreen(),'SETTINGS');}
function navigate(next){screen=next;renderedKey='';render();window.scrollTo({top:0});}

function roomHeading(r,playing=false){const g=r.game;const promoted=g&&Object.values(g.promotions).includes(g.main);const mainBadge=playing&&r.mode!=='landlord'?`<span class="main-indicator">主牌 <b>${ranks[g.main]}</b>${promoted?' · 升变':''}</span>`:'';return `<div class="room-heading"><div><h1>${esc(names[r.mode])}<span class="muted"> · ${playing?'对局':'准备室'}</span></h1>${mainBadge}</div><div class="room-heading-actions"><button class="room-number" data-action="copy"><small>房间号</small>${r.code} <small>⧉</small></button><button class="text-button" data-action="${playing&&r.game.phase!=='over'?'resign':'leave'}">${playing&&r.game.phase!=='over'?'认输结束本局':'离开房间'} ↗</button>${playing&&r.game.phase!=='over'&&r.canLeave?'<button class="text-button" data-action="leave">离开房间 ↗</button>':''}</div></div>`;}
function waiting(r) {
  const host=r.host===state.user.id;
  const seats=Array.from({length:r.capacity},(_,i)=>{
    const p=r.players[i];
    if(!p&&host)return `<button class="waiting-seat empty-seat" data-action="invite-ai"><div class="avatar">＋</div><div><strong>邀请 AI</strong><small>空座位 · ${i+1}</small></div></button>`;
    return `<div class="waiting-seat"><div class="avatar ${p?.bot?'bot':''}">${p?(p.bot?'✦':esc(p.name[0])):'＋'}</div><div><strong>${p?esc(p.name):'等待玩家加入'}</strong><small>${p?(p.id===r.host?'房主 · ':'')+(p.bot?(p.model?'模型 AI':'规则 AI'):(p.connected?'已落座':'暂时离线')):'空座位 · '+(i+1)}</small></div>${p?.bot&&host?`<button class="seat-remove" data-action="remove" data-seat="${i}" aria-label="移除AI">×</button>`:''}</div>`;
  }).join('');
  return roomHeading(r)+`<div class="waiting"><section><div class="waiting-table"><div class="waiting-center"><div class="table-logo">VGC</div></div></div><div class="waiting-seats">${seats}</div></section><aside class="waiting-info"><div class="side-panel"><h3>房间</h3><p>已落座 <b>${r.players.length} / ${r.capacity}</b><br>${r.mode==='landlord'?'三人 · 54 张 · 叫分抢地主':r.mode==='trio'?'三人 · 86 张 · 个人争先':r.mode==='basic'?'四人 · 54 张 · 对座组队':'四人 · '+(r.options.dlc?'150':'110')+' 张 · 对座组队'}<br>${r.rated?'全真人 · 本局计入积分':'含 AI · 本局为练习对局'}</p><button class="primary" data-action="start" ${!host||r.players.length!==r.capacity?'disabled':''}>开始对局 <span>→</span></button>${!host?'<p class="form-note">等待房主开始游戏。</p>':''}</div><div class="side-panel"><h3>邀请 AI</h3><button class="secondary" data-action="bot" ${!host||r.players.length===r.capacity?'disabled':''}>＋ 邀请规则 AI</button><button class="secondary" data-action="model-bot" ${!host||r.players.length===r.capacity||!state.preferences?.configured?'disabled':''}>＋ 邀请模型 AI</button><button class="text-button full" data-action="settings-api">API 设置 ↗</button><div class="divider"></div><button class="text-button" data-action="rules">阅读本桌玩法 →</button></div></aside></div>`;
}
function table(r,g) {
  const me=r.seat;
  const positions=r.capacity===3?['bottom','left','right']:['bottom','left','top','right'];
  const seats=r.players.map((p,s)=>{
    const relative=(s-me+r.capacity)%r.capacity;
    const finish=g.finished.indexOf(s);
    const role=g.mode==='landlord'?(g.landlord===s?'地主':g.landlord!==null?'农民':''):(g.mode==='trio'?'':s%2===me%2?'同队':'对手');
    const played=g.seatPlays?.[s]||(!g.seatPlays&&g.lastSeat===s?{...g.last,order:1}:null);
    const playNumber=g.playNumber??1;
    const publicCards=[];if(played)played.cards.forEach((c,i)=>{const existing=publicCards.find(x=>x.rank===c.rank&&x.suit===c.suit&&x.effective===played.ranks[i]&&x.effectiveSuit===(played.suits?.[i]||c.suit));if(existing)existing.count++;else publicCards.push({...c,effective:played.ranks[i],effectiveSuit:played.suits?.[i]||c.suit,count:1});});
    const playedCards=played?`<div class="seat-play ${!played.passed&&played.order===playNumber?'latest':'older'}" aria-label="${esc(p.name)}的最近出牌"><div class="seat-play-label">${esc(played.kind)}${played.passed?'':` · 第 ${played.order} 手${played.order===playNumber?' · 最新':''}`}</div><div class="seat-play-cards">${publicCards.map(c=>`<span class="seat-play-card ${['H','D'].includes(c.suit)||c.rank===17?'red':''}" title="${ranks[c.rank]}${suits[c.suit]}${c.rank!==c.effective||c.suit!==c.effectiveSuit?' → '+ranks[c.effective]+suits[c.effectiveSuit]:''}"><b>${ranks[c.rank]}${c.count>1?`<em>×${c.count}</em>`:''}</b><small>${suits[c.suit]}${c.rank!==c.effective||c.suit!==c.effectiveSuit?'→'+ranks[c.effective]+suits[c.effectiveSuit]:''}</small></span>`).join('')}</div></div>`:'';
    return `<div class="seat ${positions[relative]} ${g.turn===s&&g.phase!=='over'?'turn':''} ${finish>=0?'finished':''}"><div class="avatar ${p.bot?'bot':''}">${p.bot?'✦':esc(p.name[0])}</div><div><div class="seat-name">${esc(p.name)}${s===me?' · 你':''}</div><div class="seat-meta">${g.urgentLast.includes(s)?'急牌末名':g.phase==='over'&&g.counts[s]>0?'剩 '+g.counts[s]+' 张':finish>=0?'第 '+(finish+1)+' 名':g.counts[s]+' 张牌'}${!p.connected?' · 离线':g.turn===s&&g.phase==='play'?' · 出牌中':''}</div></div>${role?`<span class="seat-role">${role}</span>`:''}${playedCards}</div>`;
  }).join('');
  let center='';
  if(g.phase==='bid') center=`<div class="table-prompt">${g.turn===me?'轮到你叫分':esc(r.players[g.turn].name)+' 正在叫分'}</div><p class="table-sub">当前最高叫分 ${g.bid} · 三分直接成为地主</p>${g.turn===me?`<div class="phase-actions">${[0,1,2,3].map(n=>`<button class="${n===3?'primary':'secondary'}" data-action="bid" data-value="${n}" ${n&&n<=g.bid?'disabled':''}>${n?n+' 分':'不叫'}</button>`).join('')}</div>`:''}`;
  else if(g.phase==='setup') {
    const count={};g.hand.forEach(c=>count[c.rank]=(count[c.rank]||0)+1);
    const promotions=g.mode==='basic'?[]:Object.keys(count).filter(k=>Number(k)<16&&count[k]>=6);
    center=`<div class="table-prompt">${g.openingFirst===null?'开局亮牌':g.mode==='basic'?'开局确认':'升变确认'}</div><p class="table-sub">${g.mode==='basic'?'':'六张同点可升变 · '}${g.openingFirst===null?'亮黑桃3争先手 · 无人亮牌则随机':esc(r.players[g.openingFirst].name)+'先出'}<br>已确认 ${g.ready.length}/${r.capacity} 人</p><div class="phase-actions">${g.openingFirst===null&&g.hand.some(c=>c.suit==='S'&&c.rank===3)&&!g.reveals.includes(me)?'<button class="secondary" data-action="reveal">亮黑桃 3</button>':''}${promotions.map(k=>`<button class="secondary" data-action="promote" data-rank="${k}">升变 ${ranks[k]}</button>`).join('')}<button class="primary" data-action="confirm" ${g.ready.includes(me)?'disabled':''}>${g.ready.includes(me)?'等待其他玩家':'确认开始'}</button></div>`;
  } else if(g.phase==='rps') center=`<div class="table-prompt">猜拳定先手</div><p class="table-sub">${g.reveals.map(s=>esc(r.players[s].name)).join('、')}争夺先手</p>${g.reveals.includes(me)&&!g.ready.includes(me)?`<div class="phase-actions">${[['rock','石头'],['scissors','剪刀'],['paper','布']].map(([v,n])=>`<button class="secondary" data-action="rps" data-value="${v}">${n}</button>`).join('')}</div>`:'<p class="table-sub">等待出拳…</p>'}`;
  else if(g.phase==='tribute') {
    const t=g.tribute, offer=t.offers.find(o=>o.recipient===me&&!o.returned), canChoose=t.stage==='choose'&&t.receivers.includes(me)&&!t.offers.some(o=>o.recipient===me);
    center=`<div class="table-prompt">${t.stage==='choose'?'选择贡牌':'还牌'}</div><div class="tribute-offers">${t.offers.map(o=>`<button class="secondary" data-action="tribute-pick" data-seat="${o.donor}" ${!canChoose||o.recipient!==null?'disabled':''}>${esc(r.players[o.donor].name)} · ${ranks[o.card.rank]}${suits[o.card.suit]}${o.recipient!==null?' → '+esc(r.players[o.recipient].name):''}</button>`).join('')}</div><p class="table-sub">${t.stage==='return'&&offer?'选择一张手牌，还给 '+esc(r.players[offer.donor].name):'等待其他玩家完成进贡'}</p>`;
  }
  else if(g.phase==='play') center=g.mode==='landlord'&&!g.last&&g.bottom.length?`<div class="bottom-cards">${g.bottom.map(c=>`<span class="mini-card ${['H','D'].includes(c.suit)?'red':''}">${ranks[c.rank]}${suits[c.suit]}</span>`).join('')}</div>`:'';
  else center='<div class="table-prompt">本局已结束</div>';
  const canPlay=g.phase==='play'&&!g.finished.includes(me);
  const canReturn=g.phase==='tribute'&&g.tribute.stage==='return'&&g.tribute.offers.some(o=>o.recipient===me&&!o.returned);
  const remainingHands=g.remainingHands?`<div class="settlement-hands">${g.remainingHands.map((hand,s)=>`<section class="settlement-hand"><h3>${esc(r.players[s].name)} <small>剩余 ${hand.length} 张</small></h3><div class="settlement-cards">${hand.length?hand.map(c=>`<span class="settlement-card ${['H','D'].includes(c.suit)||c.rank===17?'red':''}">${ranks[c.rank]}${suits[c.suit]}</span>`).join(''):'<span class="muted">已出完</span>'}</div></section>`).join('')}</div>`:'';
  const result=g.phase==='over'?`<div class="result-banner"><h2>${g.winner.includes(me)?'胜利':'失败'}</h2><p>${g.winner.map(s=>esc(r.players[s].name)).join('、')} 获胜<br>${r.rated?'真人对局 · '+(g.winner.includes(me)?'+':'−')+(g.mode==='landlord'?24:20)+' 积分':'练习对局 · 不结算积分'}${g.mode!=='landlord'?(g.roundComplete?'<br>本轮结束，下轮主牌 3':'' )+'<br>出完顺序：'+(g.finished.filter(s=>g.counts[s]===0).map(s=>esc(r.players[s].name)).join(' → ')||'尚无人出完'):''}</p>${remainingHands}<div class="phase-actions"><button class="primary" data-action="start" ${r.host!==state.user.id?'disabled':''}>再来一局 →</button><button class="secondary" data-action="leave">回到主菜单</button></div>${r.host!==state.user.id?'<p class="table-sub">等待房主开始下一局。</p>':''}</div>`:'';
  const negotiation=g.negotiation?`<div class="result-banner"><h3>截牌协商</h3><p>${esc(r.players[g.negotiation.seat].name)}请求${esc(r.players[g.negotiation.target].name)}收回上一手。</p>${g.negotiation.target===me?`<div class="phase-actions"><button class="primary" data-action="accept">同意收回</button><button class="secondary" data-action="reject">保留出牌</button></div>`:'<p class="table-sub">等待对方选择。</p>'}</div>`:'';
  const responseNotice=g.response?`<div id="response-notice" role="status">可${esc(g.response.moves[0].label)}，已标记手牌。${g.turn===me?'也可改选手牌正常出牌，或不出。':'出牌或不出。'}</div>`:'';
  const controls=canReturn?`<div class="hand-controls"><button class="text-button" data-action="deselect">清空 · Esc</button><button class="primary" data-action="tribute-return" ${selected.size!==1?'disabled':''}>还牌 · Enter →</button></div>`:canPlay?`<div class="hand-controls"><div class="controls-left">${!['landlord','basic'].includes(g.mode)&&g.hand.some(c=>c.rank===14&&c.suit==='S')?`<button class="text-button" data-action="declare-wild">逐张指定${Object.keys(wildcardMap).length?' · 已设定':''}</button><select class="control-select" id="wildcard" aria-label="黑桃A代替数值"><option value="">黑桃 A · 自动配牌</option>${wildRanks().map(n=>`<option value="${n}" ${wildcard==n?'selected':''}>黑桃 A 代替 ${ranks[n]}</option>`).join('')}</select>`:''}</div><div class="controls-right"><button class="text-button" data-action="deselect">清空 · Esc</button><button class="secondary" data-action="hint">提示</button><button class="secondary" data-action="pass" ${g.negotiation||!(g.response||g.turn===me&&g.last&&g.lastSeat!==me)?'disabled':''}>不出</button><button class="primary" data-action="play" ${selected.size===0||g.negotiation||g.priority&&r.players.filter(p=>!p.bot).length===1&&!g.priority.pending.includes(me)?'disabled':''}>出牌 · Enter <span>→</span></button></div></div><div class="selection-note" id="selection-note">${selected.size?'已选择 '+selected.size+' 张牌':'选择手牌'}</div>`:'<div class="selection-note">'+(g.phase==='over'?'本局手牌已封存。':'等待开局完成后出牌。')+'</div>';
  return roomHeading(r,true)+result+negotiation+responseNotice+`<div class="table-layout"><section class="board">${seats}<div class="table-center">${center}</div></section><aside class="table-log"><div class="table-log-header"><span>牌桌动态</span><button class="text-button" data-action="rules">规则 ↗</button></div><div class="match-meta">${g.mode==='landlord'?`地主叫分 <b>${g.bid}</b>`:`${g.mode==='trio'?'三人个人争先':`我方 <b>${g.scores[me%2]}</b> · 对方 <b>${g.scores[1-me%2]}</b>`}`}<br>${r.rated?'计入积分与段位':'含 AI · 不计积分'}</div><div class="log-entries" aria-live="polite">${g.log.map(l=>`<div class="log-entry">${esc(l)}</div>`).join('')}</div></aside></div><section class="hand-area"><div class="hand-top"><strong>你的手牌 <span class="muted">/ ${g.hand.length} 张</span></strong></div><div class="hand ${g.hand.length>23?'dense':''}">${g.hand.map(c=>card(c,canPlay||canReturn,g)).join('')}</div>${controls}</section>`;
}
function showAuth(tab='login') {
  authTab=tab;
  showModal('auth',`<h2 class="modal-title">${tab==='login'?'登录':'注册'}</h2><div class="switch-tabs"><button data-action="auth-login" class="${tab==='login'?'active':''}">登录</button><button data-action="auth-register" class="${tab==='register'?'active':''}">注册</button></div><form class="form" id="auth-form"><label>玩家昵称<input name="name" required minlength="2" maxlength="18" autocomplete="username" placeholder="你的牌桌名字"></label><label>密码<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="${tab==='login'?'current-password':'new-password'}" placeholder="至少 8 个字符"></label><p class="form-error"></p><button class="primary full" type="submit">${tab==='login'?'登录':'注册'} →</button><p class="form-note">${tab==='register'?'初始 1000 积分。':''}</p></form>`,'WELCOME TO THE CLUB');
}
function showCreate(mode='landlord') {
  createMode=mode;
  const single=screen==='single',capacity=mode==='landlord'||mode==='trio'?3:4,pref=state.preferences||{};
  showModal('create',`<h2 class="modal-title">${esc(names[mode])}</h2><form class="form" id="create-form"><fieldset class="ai-invitation"><legend>${single?'AI 对手':'邀请 AI'}</legend>${single?`<p class="form-note">${capacity-1} 位 AI</p>`:`<label>邀请人数<select name="botCount">${Array.from({length:capacity},(_,n)=>`<option value="${n}">${n===0?'不邀请':n+' 位 AI'}</option>`).join('')}</select></label>`}<label>AI 类型<select name="aiType"><option value="rules">规则 AI</option><option value="model" ${pref.configured?'':'disabled'}>模型 AI ${pref.configured?'· '+esc(pref.model):'· 需配置 API'}</option></select></label></fieldset>${['standard','trio'].includes(mode)?'<label class="checkbox"><input type="checkbox" name="advancedHui">启用「回」进阶版（主体花色匹配）</label><label class="checkbox"><input type="checkbox" name="advancedDead">启用「死压」进阶版（四张截牌权）</label>':''}${['basic','standard'].includes(mode)?'<label class="checkbox"><input type="checkbox" name="tribute">启用进贡</label>':''}${mode==='standard'?'<label class="checkbox"><input type="checkbox" name="dlc">Fieldlark 三周年 DLC（额外 40 张）</label>':''}<p class="form-note">${mode==='landlord'?'三人叫分抢地主，54 张经典规则。':mode==='trio'?'三人 86 张，独立争先。':'四人对座组队，主牌从 3 开始。'}<br>全真人对局计分，含 AI 对局不计分。</p><p class="form-error"></p><button class="primary full" type="submit">${single?'开始单人游戏':'创建房间'} →</button></form>`,'SET UP YOUR TABLE');
}

async function showLeaderboard(){requireUser(async()=>{showModal('leaderboard','<h2 class="modal-title">积分榜</h2><div class="empty">加载中…</div>','THE LEADERBOARD');try{const d=await api('leaderboard');if(modalKind!=='leaderboard')return;$('#modal-content').innerHTML='<h2 class="modal-title">积分榜</h2>'+d.players.map((p,i)=>`<div class="leader-row"><span class="place">${String(i+1).padStart(2,'0')}</span><div>${esc(p.name)}${p.id===state.user.id?' · 你':''}<small>${p.rank} / ${p.wins} 胜 ${p.games} 场</small></div><span class="points">${p.points}</span></div>`).join('');}catch(e){toast(e.message);}});}
async function showProfile(){requireUser(async()=>{const u=state.user;showModal('profile',`<h2 class="modal-title">${esc(u.name)}</h2><p class="modal-desc">${u.rank}</p><div class="profile-stats"><div><strong>${u.points}</strong><small>当前积分</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div id="history"><p class="empty">正在加载战绩…</p></div><div class="divider"></div><button class="secondary full" data-action="logout">退出账号</button>`,'PLAYER ARCHIVE');try{const d=await api('history');if(modalKind!=='profile')return;$('#history').innerHTML=d.history.length?''+d.history.map(h=>`<div class="leader-row"><span>${h.delta>0?'胜':'负'}</span><div>${names[h.mode]}<small>${new Date(h.created*1000).toLocaleString('zh-CN')}</small></div><span class="points">${h.delta>0?'+':''}${h.delta}</span></div>`).join(''):'<p class="empty">暂无真人战绩。</p>';}catch(e){toast(e.message);}});}
function showRules(){
 showModal('rules',`<h2 class="modal-title">几张牌，无穷变化。</h2><div class="switch-tabs"><button class="active" data-action="rules-classic">斗地主</button><button data-action="rules-special">4A4A4 2.4</button></div><div id="rule-text" class="rules"></div>`,'THE RULEBOOK');ruleText('classic');
}
function ruleText(type){
 $$('.switch-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.action==='rules-'+type));
 $('#rule-text').innerHTML=type==='classic'?`<h3>三人 · 一副牌</h3><p>每人 17 张，余下 3 张归地主。轮流叫 1–3 分，只能叫更高的分；叫 3 分立即成为地主。全部不叫时，本实现将最后叫分玩家设为 1 分地主。</p><h3>常见牌型</h3><p>单张、对子、三张、三带一、三带一对、顺子（至少 5 张，不含 2 和王）、连对（至少 3 对）、飞机及带单/带对、四带二、四带两对。飞机的翅膀不能包含机身点数；单翼允许同点。</p><p>相同牌型、相同张数比大小。四张同点炸弹压普通牌；一小王加一大王为最大王炸。点数 3 最小，2 大于 A，大王最大。</p><h3>胜负与积分</h3><p>地主先出完则地主胜，任一农民先出完则两位农民胜。全真人牌桌胜方每人 +24，负方每人 −24，最低 0；有 AI 不结算积分。</p>`:`<h3>标准版与变体</h3><p>标准版四人 110 张：两副牌和两张急牌。对座组队，主牌初始为 3，点数大于 2、小于小王。主牌可按原点数组成顺子、连对和飞机；2 和王不参与连续牌型。</p><p>三人 86 张：去掉两副牌的黑桃 3–K、两张小王和一张急牌，加入一张大王；每人独立争先。基础版四人 54 张：一副牌，三张起炸，顺子至少三张、连对至少两对，不允许任何带牌组合，仅额外支持勾、叉、4A4，同样亮黑桃 3 定先手，不使用升变。</p><p>Fieldlark DLC 额外加入黑桃 A ×5、Delta A ×2、Delta 2–K 各2张、大小王各1张、急牌×7，共额外40张。可在创建标准房间时选择。</p><h3>开局</h3><p>可展示至少六张原生同点牌进行升变，多人升变取自然点数最大的牌为主。选择亮黑桃 3 的玩家争夺先手，多人亮牌通过猜拳决出一人；都不亮时随机选择先手。所有玩家确认后开始。下一局由上一局最先出完者先发牌、先出牌。</p><h3>带牌</h3><p>标准版与三人版：N 张同点牌可带 1 至 N−2 个单位（N 至少为 3）。单位按单牌或对子计数；单牌附件按实际张数计算，允许混合单牌、对子及更多同点牌。例如五带三可带一单加一对，六带四可带两单加一对或一单加三张同点牌；全部对子也可按张数跟单牌附件。附件不能与主组同点。连续两组及以上同样张数的主体也可组成飞机：每组四张可带一或两个单位，每组五张可带一至三个单位，以此类推；各组带牌单位数及类型一致。相同主组张数、附件单位数与单位类型才可比大小。基础版不允许带牌。</p><h3>特殊出牌</h3><table><tr><th>出法</th><th>条件与效果</th></tr><tr><td>叉</td><td>两张同点，管同点单张；叉后只能勾，无人勾则叉牌者继续出牌。</td></tr><tr><td>勾</td><td>一张同点，管叉出的两张牌；勾后可用同点对子再叉，再用同点单牌勾；无人再叉则勾牌者自由出牌。</td></tr><tr><td>点</td><td>一张同点，管非勾叉对子；点 2 或主直接获牌权。</td></tr><tr><td>压</td><td>一张 2、主或王，管点牌，直接获牌权。</td></tr><tr><td>死压</td><td>三张同点，管非勾叉对子，直接获牌权。进阶版可用四张同点截获死压牌权。</td></tr><tr><td>回</td><td>同花色单牌管小于 2 的非特殊单牌，每轮一次。进阶版要求相同牌型、张数，主体各点数组的花色构成逐组相同，带牌附件任意；不比较点数。王、2 和主不能作为回牌或被回牌的主体，附件只需符合带牌规则。</td></tr><tr><td>黑桃 A</td><td>可以作为普通 A 单出；组合中可代替任意非王牌，不能单张替代其他点数。自动配牌或手动指定替代点数${state.features?.wildUrgent?'；代急牌时出牌即可选择赠送目标。':'。'}</td></tr><tr><td>急牌</td><td>选一张急牌和一张非急牌，在自己的出牌回合赠给任一仍在场玩家，公开显示赠送牌的花色与点数；急牌弃掉，不占出牌次数，可继续正常出牌或使用急牌。仅剩一张急牌自动末名。</td></tr></table><h3>炸弹与 4A4A4</h3><p>四炸 &lt; 双王 &lt; 五炸 &lt; 六炸 &lt; 三王 &lt; 七炸 &lt; 八炸 &lt; 四王 &lt; 九炸 &lt; 十炸 &lt; 基础 4A4A4 &lt; 更大 4A4A4。炸弹压普通及点牌；叉只能用勾管，勾可以再叉再勾。更多同点炸弹继续按张数排列。</p><p>标准 4A4A4 至少三张 4 和两张 A，4 的数量必须多于 A；等级只计算能配齐的组合：至少三张 4、两张 A，使用全部 A 和比 A 多一张的 4 计级；额外的 4 可以一起出，但不升级，例如 44444AA 与 444AA 同级。基础版最低两张 4 和一张 A。</p><h3>抢牌权与协商</h3><p>叉、勾、点、压、死压有优先管牌机会；单人悬浮提示并自动选中可管的手牌，直接点击出牌，或点不出放弃，决定后才继续 AI。多人同样提示并标记，正常轮转，尚无人后续出牌时直接管牌，已有一人出牌时点击出牌自动请求对方收回；已有两名玩家出牌则视为放弃此次机会。叉出的对子只能用同点单牌勾；无人勾则叉牌者继续，勾后可以再叉再勾，无人再叉则勾牌者自由出牌。若上一手玩家已出完，特殊出法可在原下一家行动之前截牌。原下一家已经出牌时，可选牌和特殊出法申请协商；对方同意才回退上一手并执行截牌。已有两人完成时不得协商。</p><h3>进贡</h3><p>创建房间时可勾选启用，默认关闭。启用后，下一局发牌后，被抓住的玩家交出最大普通牌（急牌不参与）。抓一人时首位出完者收贡；抓两人时胜方对家各选一张贡牌。收贡者分别还任意一张手牌给对应进贡者，完成后才能开局。</p><h3>胜负、主牌与爆牌</h3><p>其他在场玩家都不出时，牌权持有者可任意领出合法牌型。四人局已出完者的最后一手无人管牌时，牌权交给其仍在场的对家。四人局首位出完者所在队获胜，其对家出完后剩 1 人升 1 级、剩 2 人升 2 级、无人剩余不升级；败队不升级。两队各自从 3 升至 A，超过 A 停在 A；以 A 为主获胜后本轮结束，下一轮两队归零、主牌回 3 并重新亮黑桃 3。轮内后续对局不再亮黑桃 3，下一局使用胜队的主牌。三人第一位出完者胜，以个人累计胜局循环决定下一局主牌。</p><p>手牌变动后若不超过 10 张，服务端自动公布剩余张数。“分”玩法停用。真人 4A4A4 胜方 +20、负方 −20，有 AI 不结算积分。认输直接结束本局，队友共同判负。</p><h3>段位</h3><p>800 以下纸牌学徒，800–1099 墨线新秀，1100–1399 银笔高手，1400–1799 黑金大师，1800–2399 牌桌宗师，2400 起无冕传奇。</p>`;
}
function $$(s){return [...document.querySelectorAll(s)];}
async function gameAction(action,extra={}){if(!state.room)return;return await mutation('action',{action,revision:state.room.revision,...extra});}
function wildRank(value){return typeof value==='object'?value?.rank:value;}
function wildcardPayload(){
  const map=Object.fromEntries(Object.entries(wildcardMap).filter(([id])=>selected.has(id)));
  const declaration=Object.keys(map).length?map:(wildcard?Number(wildcard):undefined);
  if(selected.size===1){const c=state.room?.game?.hand.find(c=>selected.has(c.id));if(c?.rank===14&&c.suit==='S'&&(typeof declaration==='object'?wildRank(declaration[c.id])===14:declaration===14))return undefined;}
  return declaration;
}
function urgentSelected(){
 const wild=wildcardPayload();
 return state.room.game.hand.some(c=>selected.has(c.id)&&(c.rank===18||c.rank===14&&c.suit==='S'&&(typeof wild==='object'?wildRank(wild[c.id])===18:wild===18)));
}
function showWildcard(){
  const wild=state.room?.game?.hand.filter(c=>selected.has(c.id)&&c.suit==='S'&&c.rank===14)||[];
  if(!wild.length||selected.size<2){toast('先选择至少两张牌，其中包含黑桃 A。');return;}
  showModal('wildcard',`<h2 class="modal-title">黑桃 A 配牌</h2><p class="modal-desc">每张黑桃 A 可以独立代替非王牌。选择 A 表示保留原点数${state.features?.wildUrgent?'；选择急牌后出牌即可赠牌。':'。'}</p><form class="form" id="wildcard-form">${wild.map((c,i)=>`<label>第 ${i+1} 张黑桃 A<select name="rank:${esc(c.id)}">${wildRanks().map(n=>`<option value="${n}" ${n===(wildRank(wildcardMap[c.id])||14)?'selected':''}>${ranks[n]}</option>`).join('')}</select><select name="suit:${esc(c.id)}" aria-label="替代花色">${Object.entries(suits).filter(([s])=>['S','H','C','D'].includes(s)||s==='T'&&state.room.options.dlc).map(([s,label])=>`<option value="${s}" ${s===(wildcardMap[c.id]?.suit||'S')?'selected':''}>${label}</option>`).join('')}</select></label>`).join('')}<button class="primary full" type="submit">确认配牌 →</button></form>`,'WILDCARD DECLARATION');
}
function selectionUpdate(){
 $$('.hand .card').forEach(b=>{b.classList.toggle('selected',selected.has(b.dataset.card));b.setAttribute('aria-pressed',selected.has(b.dataset.card));});
 const returned=$('[data-action="tribute-return"]');if(returned)returned.disabled=selected.size!==1||state.room.audioWaiting;
 const btn=$('[data-action="play"]');if(btn)btn.disabled=state.room.audioWaiting||!selected.size||!!state.room?.game?.negotiation||!!state.room?.game?.priority&&state.room.players.filter(p=>!p.bot).length===1&&!state.room.game.priority.pending.includes(state.room.seat);
 const note=$('#selection-note');if(note){const text=note.firstChild;if(text?.nodeType===Node.TEXT_NODE)text.textContent=(selected.size?'已选择 '+selected.size+' 张牌':'选择手牌')+(state.room.game.mode==='landlord'?'':' ');}
}
let cardSweep=null, suppressCardClick=false;
function sweepCard(card){
 if(!card||!cardSweep||cardSweep.visited.has(card.dataset.card))return;
 cardSweep.visited.add(card.dataset.card);
 cardSweep.selecting?selected.add(card.dataset.card):selected.delete(card.dataset.card);
}
document.addEventListener('pointerdown',e=>{
 cardSweep=null;suppressCardClick=false;
 if(e.pointerType!=='mouse'||e.button!==0)return;
 const card=e.target.closest('.hand [data-card]');if(!card)return;
 cardSweep={pointerId:e.pointerId,selecting:!selected.has(card.dataset.card),visited:new Set(),x:e.clientX,y:e.clientY};
 suppressCardClick=true;sweepCard(card);selectionUpdate();e.preventDefault();
});
document.addEventListener('pointermove',e=>{
 if(!cardSweep||e.pointerId!==cardSweep.pointerId||!(e.buttons&1))return;
 const {x,y}=cardSweep, steps=Math.max(1,Math.ceil(Math.hypot(e.clientX-x,e.clientY-y)/8));
 for(let i=1;i<=steps;i++)sweepCard(document.elementFromPoint(x+(e.clientX-x)*i/steps,y+(e.clientY-y)*i/steps)?.closest('.hand [data-card]'));
 cardSweep.x=e.clientX;cardSweep.y=e.clientY;selectionUpdate();e.preventDefault();
});
document.addEventListener('pointerup',()=>{cardSweep=null;});
document.addEventListener('pointercancel',()=>{cardSweep=null;suppressCardClick=false;});
document.addEventListener('click',async e=>{
 const c=e.target.closest('[data-card]');if(c){if(e.detail&&suppressCardClick){suppressCardClick=false;return;}selected.has(c.dataset.card)?selected.delete(c.dataset.card):selected.add(c.dataset.card);selectionUpdate();return;}
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
 case 'settings':case 'settings-api':settingsTab=action==='settings-api'?'api':'account';if(state.room)showSettingsModal();else navigate('settings');break;
 case 'settings-tab':settingsTab=b.dataset.tab;if(state.room)showSettingsModal();else{renderedKey='';render();}break;
 case 'lobby':if(state.room)toast('当前仍在房间中。请离开房间后返回主菜单。');else {closeModal();navigate('home');}break;
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
 case 'leave':await mutation('leave');if(!state.room)navigate('home');break;
 case 'resign':showModal('resign','<h2 class="modal-title">认输结束这一局？</h2><p class="modal-desc">本局立即结束。真人对局将结算负分；组队时你的队友也会判负。</p><div class="phase-actions"><button class="secondary" data-action="close">继续打牌</button><button class="primary" data-action="resign-confirm">确认认输</button></div>','END THIS MATCH');break;
 case 'resign-confirm':await mutation('resign');closeModal();break;
 case 'tribute-pick':await gameAction('tribute-pick',{target:Number(b.dataset.seat)});break;
 case 'tribute-return':if(await gameAction('tribute-return',{ids:[...selected]})){selected.clear();renderedKey='';render();}break;
 case 'bid':await gameAction('bid',{value:Number(b.dataset.value)});break;
 case 'reveal':case 'confirm':case 'pass':case 'accept':case 'reject':await gameAction(action);break;
 case 'promote':await gameAction('promote',{rank:Number(b.dataset.rank)});break;
 case 'rps':await gameAction('rps',{value:b.dataset.value});break;
 case 'declare-wild':showWildcard();break;
 case 'deselect':selected.clear();selectionUpdate();break;
 case 'hint':{
   const result=await api('hint',{});hintMoves=result.moves;if(!hintMoves.length){toast('未找到提示方案，可手动选牌或选择不出。');return;}
   const move=hintMoves[hintIndex++%hintMoves.length];selected=new Set(move.ids);wildcard='';wildcardMap=move.wildcard||{};renderedKey='';render();toast(move.label+' · 再点提示切换方案');break;
 }
 case 'gift-player':{
   const args={ids:[...selected],target:Number(b.dataset.seat)};const wild=wildcardPayload();if(wild!==undefined)args.wildcard=wild;
   const result=await gameAction('urgent',args);if(result){closeModal();wildcard='';wildcardMap={};renderedKey='';render();toast('赠牌完成，不占出牌次数，可以继续出牌。');}break;
 }
 case 'play':{
   if(urgentSelected()){if(state.room.game.turn!==state.room.seat){toast('请在自己的出牌回合使用急牌。');return;}showModal('gift',`<h2 class="modal-title">赠送给谁？</h2><p class="modal-desc">选中的急牌将弃掉，另一张牌交给你选择的玩家。赠牌不占出牌次数。</p><div class="gift-players">${state.room.players.map((p,s)=>s!==state.room.seat&&!state.room.game.finished.includes(s)?`<button class="secondary" data-action="gift-player" data-seat="${s}">${esc(p.name)} <small>${state.room.game.counts[s]} 张手牌</small></button>`:'').join('')}</div>`,'URGENT GIFT');break;}
   const args={ids:[...selected]};const wild=wildcardPayload();if(wild!==undefined)args.wildcard=wild;
   await gameAction('auto',args);break;
 }
 }
 }catch(error){toast(error.message);}
});
document.addEventListener('input',e=>{const key=e.target.dataset.volume;if(key){gameAudio.setVolume(key,e.target.value/100);$('#volume-'+key).textContent=e.target.value+'%';}});
document.addEventListener('keydown',e=>{
 if(e.repeat||modal.open||e.target.closest('input,textarea,select,[contenteditable="true"]'))return;
 const action=e.key==='Enter'?(state.room?.game?.phase==='tribute'?'tribute-return':'play'):e.key==='Escape'?'deselect':null;
 if(!action)return;const button=$(`[data-action="${action}"]`);
 if(button&&!button.disabled){e.preventDefault();button.click();}
});
document.addEventListener('change',e=>{
 if(e.target.id==='wildcard'){wildcard=e.target.value;wildcardMap={};}
});
document.addEventListener('submit',async e=>{
 e.preventDefault();const f=e.target;
 if(f.id==='join-form'){const code=$('#join-code').value;requireUser(async()=>{await mutation('join',{code,...(screen==='single'?{single:true}:{})});});return;}
 const error=$('.form-error',f);const submit=$('button[type=submit]',f);if(submit)submit.disabled=true;
 try{
 if(f.id==='wildcard-form'){const data=new FormData(f);wildcardMap=Object.fromEntries([...data].filter(([name])=>name.startsWith('rank:')).map(([name,v])=>{const id=name.slice(5);return [id,{rank:Number(v),suit:data.get('suit:'+id)}];}));wildcard='';closeModal();renderedKey='';render();}
 if(f.id==='auth-form'){const data=Object.fromEntries(new FormData(f));await api(authTab,data);closeModal();renderedKey='';await sync();toast(authTab==='login'?'欢迎回到VGC。':'注册成功，牌桌在等你。');}
 if(f.id==='create-form'){await api('create',{mode:createMode,options:{advancedHui:f.elements.advancedHui?.checked||false,advancedDead:f.elements.advancedDead?.checked||false,dlc:f.elements.dlc?.checked||false,tribute:f.elements.tribute?.checked||false}});const count=screen==='single'?(createMode==='landlord'||createMode==='trio'?2:3):Number(f.elements.botCount.value);for(let i=0;i<count;i++)await api('bot',{model:f.elements.aiType.value==='model'});if(screen==='single')await api('start',{});closeModal();await sync();}
 if(f.id==='api-settings-form'){await api('model-settings',Object.fromEntries(new FormData(f)));f.reset();await sync();if(state.room)showSettingsModal();toast('模型 API 已保存。');}
 if(f.id==='account-form'){await api('account',Object.fromEntries(new FormData(f)));await sync();if(state.room)showSettingsModal();toast('账号信息已更新。');}
 }catch(e){if(error)error.textContent=e.message;else toast(e.message);}finally{if(submit)submit.disabled=false;}
});
modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
modal.addEventListener('close',()=>{modalKind='';});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){clearTimeout(pollTimer);poll();}});
render();poll();
