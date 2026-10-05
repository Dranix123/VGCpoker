'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {landlord:'斗地主',standard:'4A4A4',trio:'4A4A4 · 三人',basic:'4A4 · 基础'};
const ranks = {3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'10',11:'J',12:'Q',13:'K',14:'A',15:'2',16:'小王',17:'大王',18:'急'};
const suits = {S:'♠',H:'♥',C:'♣',D:'♦',T:'Δ',J:'✦',U:'↗'};
const actions = {play:'普通出牌',cross:'叉',hook:'勾',dot:'点',press:'压',dead:'死压',dead4:'进阶死压',hui:'回',urgent:'急牌赠牌'};
let state = {user:null,room:null}, selected = new Set(), playType = 'play', wildcard = '', wildcardMap = {}, giftTarget = '', hintIndex = 0, hintMoves = [], renderedKey = '', lastPhase = '', busy = false, authTab = 'login', createMode = 'landlord', modalKind = '', connected = false;
let pollTimer, toastTimer, screen='home', settingsTab='account';
const modal = $('#modal');
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3500); }
async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败，请重试。');
  return data;
}
async function mutation(path, body = {}) {
  if (busy) return;
  busy = true;
  try { const result = await api(path,body); if ('room' in result) {state.room = result.room; renderedKey = ''; render();} await sync(); return result; }
  catch(e) {toast(e.message); await sync();}
  finally {busy = false;}
}
async function sync() {
  try {
    const next = await api('state');
    const oldRoom = state.room?.code;
    state = next; connected = true;
    if (oldRoom !== state.room?.code) {selected.clear(); playType='play'; wildcard='';wildcardMap={};}
    const available = new Set(state.room?.game?.hand.map(c=>c.id) || []);
    selected = new Set([...selected].filter(id=>available.has(id)));
    render();
  } catch(e) {connected = false;}
  $('#connection').classList.toggle('offline', !connected);
  $('#connection').innerHTML = `<i></i>${connected?'牌桌在线':'连接中…'}`;
}
async function poll() {await sync(); pollTimer = setTimeout(poll, document.hidden ? 2500 : 850);}
function showModal(kind, content, kicker = 'PAPER CLUB') {modalKind=kind; $('#modal-kicker').textContent=kicker; $('#modal-content').innerHTML=content; if(!modal.open) modal.showModal();}
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
  $('#account').innerHTML = u ? `${esc(u.name)} <span>♠</span>` : '登录 / 注册 <span>↗</span>';
  $('#account').dataset.action = u?'settings':'auth';
  document.body.classList.toggle('home-screen',!r&&screen==='home');
  document.body.classList.toggle('in-game',!!g);
  $('#breadcrumb').innerHTML = `俱乐部 <span>/</span> ${r?`${esc(names[r.mode])} <span>/</span> ${g?'牌桌':'房间'}`:'游戏大厅'}`;
  if(!r)$('#breadcrumb').textContent=({home:'',create:'创建房间 / 选择玩法',single:'单人模式 / 选择玩法',settings:'设置'})[screen];
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
  if(g && lastPhase!==g.phase){hintMoves=[];hintIndex=0;lastPhase=g.phase;}
  if(!g)lastPhase='';

}
function lobby() {
  const u=state.user;
  return `<section class="game-home"><div class="home-copy"><p class="eyebrow">A LITTLE LUCK. A LITTLE SKILL.</p><h1 class="home-title">纸间<span>扑克牌俱乐部</span></h1><p class="home-quote">落座，世界只剩这一手牌。</p><div class="main-menu"><button class="main-menu-item" data-action="open-create"><span class="menu-number">01</span><span class="menu-label">创建房间<small>与朋友，开一场好局。</small></span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="open-single"><span class="menu-number">02</span><span class="menu-label">单人模式<small>和 AI 过过招，慢慢成为高手。</small></span><span class="menu-arrow">↗</span></button><button class="main-menu-item" data-action="settings"><span class="menu-number">03</span><span class="menu-label">设置<small>账号信息 / 模型 API</small></span><span class="menu-arrow">↗</span></button></div><div class="home-bottom"><span>${u?esc(u.name)+' · '+esc(u.rank)+' / '+u.points+' 积分':'初次来访？注册一个账号，留个座位。'}</span><button class="text-button" data-action="${u?'leaderboard':'auth'}">${u?'积分榜':'登录 / 注册'} ↗</button></div></div><div class="home-scene" aria-hidden="true"><div class="sketch-ring ring-one"></div><div class="sketch-ring ring-two"></div><span class="scene-small">THE NEXT HAND IS YOURS.</span><div class="home-card-fan">${[['4','♣'],['A','♥'],['4','♠'],['A','♦'],['4','♣']].map(([r,s],i)=>`<div class="home-art-card ${s==='♥'||s==='♦'?'red':''}" data-index="${i}"><span>${r}<small>${s}</small></span><b>${s}</b><i>${r}<small>${s}</small></i></div>`).join('')}</div><div class="scene-signature">几张纸，一场好局。<span>♠ <b class="red">♥</b> ♣ <b class="red">♦</b></span></div><span class="scene-edition">PAPER CLUB<br><b>NO. 01 / 2026</b></span></div></section>`;
}
function flowScreen(){
 const single=screen==='single';
 return `<div class="flow-heading"><button class="text-button" data-action="home">← 返回主菜单</button><p class="eyebrow">${single?'SOLO PRACTICE':'PLAY WITH FRIENDS'}</p><h1>${single?'这一局，练练手。':'选个玩法，叫上朋友。'}</h1><p class="modal-desc">${single?'选择玩法，再挑选你的 AI 对手。所有单人对局均不计积分。':'创建牌桌后分享房间号，朋友登录后即可加入。'}</p></div><div class="mode-layout"><section class="mode-grid">${[['landlord','01','经典斗地主','三人 / 54 张','叫分争地主，联手定胜负。','♠'],['standard','02','4A4A4 标准版','四人 / 110 张 / 2.4','勾叉点压，见招拆招。','4A'],['trio','03','4A4A4 三人版','三人 / 86 张','各自为战，争先出完。','♧'],['basic','04','4A4 基础版','四人 / 54 张','基础勾叉，三张起炸。','4']].map(([m,i,t,n,d,mark])=>`<button class="mode-card" data-action="choose-mode" data-mode="${m}"><span class="mode-number">${i} / ${m.toUpperCase()}</span><span class="mode-symbol">${mark}</span><h2>${t}</h2><p>${d}</p><div class="mode-foot"><small>${n}</small><span>选择 →</span></div></button>`).join('')}</section><aside class="flow-aside">${single?`<div class="side-panel"><p class="eyebrow">YOUR PRACTICE TABLE</p><h3>从容落座，自在练牌。</h3><p>规则 AI 随时陪练。<br>想与模型对弈？先在设置中保存 API，再选择模型 AI。</p><button class="text-button" data-action="settings-api">模型 API 设置 ↗</button><div class="divider"></div><p>AI 只使用合法出牌。<br>练习不会影响积分与段位。</p></div>`:`<div class="side-panel"><p class="eyebrow">JOIN A TABLE</p><h3>朋友已经开好牌桌？</h3><p>输入六位房间号，直接入座。</p><form id="join-form"><input id="join-code" class="join-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required placeholder="— — —" aria-label="六位房间号" autocomplete="off"><button class="secondary full" type="submit">加入房间 →</button></form><div class="divider"></div><p>全真人牌桌结算积分。<br>房主也可以添加 AI 补齐空座。</p></div>`}</aside></div>`;
}
function settingsScreen(){
 const u=state.user, pref=state.preferences||{};
 const tabs=[['account','账号信息'],['api','模型 API'],['archive','积分与战绩']];
 let content='';
 if(!u)content='<h2>留一个自己的座位。</h2><p class="modal-desc">登录后管理账号、保存模型 API 和查看战绩。</p><button class="primary" data-action="auth">登录 / 注册 →</button>';
 else if(settingsTab==='account')content=`<h2>账号信息</h2><p class="modal-desc">${esc(u.rank)} · ${u.points} 积分 · ${u.games} 场真人对局</p><form class="form" id="account-form"><label>玩家昵称<input name="name" value="${esc(u.name)}" required minlength="2" maxlength="18" autocomplete="username"></label><label>当前密码<input name="currentPassword" type="password" required autocomplete="current-password" placeholder="保存信息时验证身份"></label><label>新密码<input name="newPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" placeholder="留空表示保留当前密码"></label><p class="form-note">修改密码后，其他设备的登录会话将退出。</p><p class="form-error"></p><button class="primary" type="submit">保存账号信息 →</button></form><div class="divider"></div><button class="text-button" data-action="logout">退出账号 ↗</button>`;
 else if(settingsTab==='api')content=`<h2>模型 API</h2><p class="modal-desc">${pref.configured?'已配置 · 密钥已保存到本次服务的内存中':'让你喜欢的模型坐上牌桌。支持兼容 Chat Completions 的 HTTPS API。'}</p><form class="form" id="api-settings-form"><label>API 基础地址<input name="endpoint" type="url" required value="${esc(pref.endpoint||'')}" placeholder="https://api.example.com/v1"></label><label>模型名称<input name="model" required maxlength="100" value="${esc(pref.model||'')}" placeholder="模型 ID"></label><label>API 密钥<input name="key" type="password" ${pref.configured?'':'required'} autocomplete="off" placeholder="${pref.configured?'密钥已保存；留空表示不更换':'输入你的 API Key'}"></label><p class="form-note">模型只看到自己的手牌与公开局面。无效回答或请求失败时使用规则 AI。密钥不会返回浏览器或写入数据库，服务重启后需要重新配置。模型提供商可能按请求收费。</p><p class="form-error"></p><button class="primary" type="submit">保存模型配置 →</button></form>${pref.configured?'<div class="divider"></div><button class="text-button" data-action="clear-api">清除 API 配置 ↗</button>':''}`;
 else content=`<h2>每一分，都是一场好局。</h2><p class="modal-desc">仅全真人对局结算积分；含 AI 的对局自在练习。</p><div class="profile-stats"><div><strong>${u.points}</strong><small>${u.rank}</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div class="phase-actions"><button class="secondary" data-action="profile">最近战绩 →</button><button class="secondary" data-action="leaderboard">查看积分榜 →</button></div>`;
 return `<div class="flow-heading"><button class="text-button" data-action="home">← 返回主菜单</button><p class="eyebrow">MAKE YOURSELF AT HOME</p><h1>设置</h1></div><div class="settings-layout"><nav class="settings-tabs">${tabs.map(([k,t])=>`<button class="${settingsTab===k?'active':''}" data-action="settings-tab" data-tab="${k}">${t}<span>→</span></button>`).join('')}<div class="divider"></div><button data-action="rules">玩法手册 <span>↗</span></button></nav><section class="settings-content">${content}</section></div>`;
}
function showSettingsModal(){showModal('settings',settingsScreen(),'SETTINGS');}
function navigate(next){screen=next;renderedKey='';render();window.scrollTo({top:0});}

function roomHeading(r,playing=false){return `<div class="room-heading"><div><p class="eyebrow">${playing?'CARDS ON THE TABLE':'WAITING FOR FRIENDS'}</p><h1>${esc(names[r.mode])}<span class="muted"> · ${playing?'对局':'准备室'}</span></h1></div><div class="room-heading-actions"><button class="room-number" data-action="copy"><small>房间号</small>${r.code} <small>⧉</small></button><button class="text-button" data-action="${playing&&r.game.phase!=='over'?'resign':'leave'}">${playing&&r.game.phase!=='over'?'认输结束本局':'离开房间'} ↗</button></div></div>`;}
function waiting(r) {
  const host=r.host===state.user.id;
  const seats=Array.from({length:r.capacity},(_,i)=>{
    const p=r.players[i];
    return `<div class="waiting-seat"><div class="avatar ${p?.bot?'bot':''}">${p?(p.bot?'✦':esc(p.name[0])):'＋'}</div><div><strong>${p?esc(p.name):'等待玩家加入'}</strong><small>${p?(p.id===r.host?'房主 · ':'')+(p.bot?(p.model?'模型 AI':'规则 AI'):(p.connected?'已落座':'暂时离线')):'空座位 · '+(i+1)}</small></div>${p?.bot&&host?`<button class="seat-remove" data-action="remove" data-seat="${i}" aria-label="移除AI">×</button>`:''}</div>`;
  }).join('');
  return roomHeading(r)+`<div class="waiting"><section><div class="waiting-table"><div class="waiting-center"><div class="table-logo">纸 间</div><p>好局，总值得等一等。</p></div></div><div class="waiting-seats">${seats}</div></section><aside class="waiting-info"><div class="side-panel"><p class="eyebrow">THE NEXT HAND</p><h3>等人齐，就开牌</h3><p>已落座 <b>${r.players.length} / ${r.capacity}</b><br>${r.mode==='landlord'?'三人 · 54 张 · 叫分抢地主':r.mode==='trio'?'三人 · 86 张 · 个人争先':r.mode==='basic'?'四人 · 54 张 · 对座组队':'四人 · '+(r.options.dlc?'150':'110')+' 张 · 对座组队'}<br>${r.rated?'全真人 · 本局计入积分':'含 AI · 本局为练习对局'}</p><button class="primary" data-action="start" ${!host||r.players.length!==r.capacity?'disabled':''}>开始对局 <span>→</span></button>${!host?'<p class="form-note">等待房主开始游戏。</p>':''}</div><div class="side-panel"><p class="eyebrow">PRACTICE MAKES PERFECT</p><h3>找个练习搭子</h3><p>规则 AI 随时落座。模型 AI 使用设置中保存的 API。</p><button class="secondary" data-action="bot" ${!host||r.players.length===r.capacity?'disabled':''}>＋ 加入规则 AI</button><button class="secondary" data-action="model-bot" ${!host||r.players.length===r.capacity||!state.preferences?.configured?'disabled':''}>＋ 加入模型 AI</button><button class="text-button full" data-action="settings-api">API 设置 ↗</button><div class="divider"></div><button class="text-button" data-action="rules">阅读本桌玩法 →</button></div></aside></div>`;
}
function table(r,g) {
  const me=r.seat;
  const positions=r.capacity===3?['bottom','left','right']:['bottom','left','top','right'];
  const seats=r.players.map((p,s)=>{
    const relative=(s-me+r.capacity)%r.capacity;
    const finish=g.finished.indexOf(s);
    const role=g.mode==='landlord'?(g.landlord===s?'地主':g.landlord!==null?'农民':''):(g.mode==='trio'?'':s%2===me%2?'同队':'对手');
    return `<div class="seat ${positions[relative]} ${g.turn===s&&g.phase!=='over'?'turn':''} ${finish>=0?'finished':''}"><div class="avatar ${p.bot?'bot':''}">${p.bot?'✦':esc(p.name[0])}</div><div><div class="seat-name">${esc(p.name)}${s===me?' · 你':''}</div><div class="seat-meta">${g.urgentLast.includes(s)?'急牌末名':finish>=0?'第 '+(finish+1)+' 名':g.counts[s]+' 张牌'}${!p.connected?' · 离线':g.turn===s&&g.phase==='play'?' · 出牌中':''}</div></div>${role?`<span class="seat-role">${role}</span>`:''}</div>`;
  }).join('');
  let center='';
  if(g.phase==='bid') center=`<div class="table-prompt">${g.turn===me?'轮到你叫分':esc(r.players[g.turn].name)+' 正在叫分'}</div><p class="table-sub">当前最高叫分 ${g.bid} · 三分直接成为地主</p>${g.turn===me?`<div class="phase-actions">${[0,1,2,3].map(n=>`<button class="${n===3?'primary':'secondary'}" data-action="bid" data-value="${n}" ${n&&n<=g.bid?'disabled':''}>${n?n+' 分':'不叫'}</button>`).join('')}</div>`:''}`;
  else if(g.phase==='setup') {
    const count={};g.hand.forEach(c=>count[c.rank]=(count[c.rank]||0)+1);
    const promotions=Object.keys(count).filter(k=>Number(k)<16&&count[k]>=6);
    center=`<div class="table-prompt">${g.openingFirst===null?'开局亮牌':'升变确认'}</div><p class="table-sub">六张同点可升变 · ${g.openingFirst===null?'亮黑桃3争先手':esc(r.players[g.openingFirst].name)+'先出'}<br>已确认 ${g.ready.length}/${r.capacity} 人</p><div class="phase-actions">${g.openingFirst===null&&g.hand.some(c=>c.suit==='S'&&c.rank===3)&&!g.reveals.includes(me)?'<button class="secondary" data-action="reveal">亮黑桃 3</button>':''}${promotions.map(k=>`<button class="secondary" data-action="promote" data-rank="${k}">升变 ${ranks[k]}</button>`).join('')}<button class="primary" data-action="confirm" ${g.ready.includes(me)?'disabled':''}>${g.ready.includes(me)?'等待其他玩家':'确认开始'}</button></div>`;
  } else if(g.phase==='rps') center=`<div class="table-prompt">猜拳定先手</div><p class="table-sub">${g.reveals.map(s=>esc(r.players[s].name)).join('、')}争夺先手</p>${g.reveals.includes(me)&&!g.ready.includes(me)?`<div class="phase-actions">${[['rock','石头'],['scissors','剪刀'],['paper','布']].map(([v,n])=>`<button class="secondary" data-action="rps" data-value="${v}">${n}</button>`).join('')}</div>`:'<p class="table-sub">等待出拳…</p>'}`;
  else if(g.last) center=`<div class="table-caption">${esc(r.players[g.lastSeat].name)} · ${esc(g.last.kind)}${g.last.special==='play'?'':' · 特殊出牌'}${g.last.cards.some((c,i)=>c.rank!==g.last.ranks[i])?' · 混子已配牌':''}</div><div class="played-cards">${g.last.cards.map(c=>card(c)).join('')}</div><p class="table-sub">${g.turn===me?(g.last.direct?'获得牌权 · 自由出牌':'轮到你回应'):'等待 '+esc(r.players[g.turn].name)+' 出牌'}</p>`;
  else center=`<div class="table-prompt">${g.phase==='over'?'本局已结束':g.turn===me?'你的回合':'轮到 '+esc(r.players[g.turn].name)}</div><p class="table-sub">${g.phase==='over'?'感谢同桌，下一局见。':'自由出牌 · 选择手牌后出牌'}</p>${g.mode==='landlord'&&g.bottom.length?`<div class="bottom-cards">${g.bottom.map(c=>`<span class="mini-card ${['H','D'].includes(c.suit)?'red':''}">${ranks[c.rank]}${suits[c.suit]}</span>`).join('')}</div>`:''}`;
  const canPlay=g.phase==='play'&&!g.finished.includes(me);
  const special=g.mode==='landlord'?['play']:g.mode==='basic'?['play','cross','hook']:['play','cross','hook','dot','press','dead',...(g.options.advancedDead?['dead4']:[]),'hui','urgent'];
  if(!special.includes(playType))playType='play';
  const result=g.phase==='over'?`<div class="result-banner"><p class="eyebrow">ONE MORE GOOD HAND</p><h2>${g.winner.includes(me)?'这一局，赢了。':'下一局，再来。'}</h2><p>${g.winner.map(s=>esc(r.players[s].name)).join('、')} 获胜<br>${r.rated?'真人对局 · '+(g.winner.includes(me)?'+':'−')+(g.mode==='landlord'?24:20)+' 积分':'练习对局 · 不结算积分'}${g.mode!=='landlord'?'<br>本局名次：'+g.finished.map(s=>esc(r.players[s].name)).join(' → '):''}</p><div class="phase-actions"><button class="primary" data-action="start" ${r.host!==state.user.id?'disabled':''}>再来一局 →</button><button class="secondary" data-action="leave">回到主菜单</button></div>${r.host!==state.user.id?'<p class="table-sub">等待房主开始下一局。</p>':''}</div>`:'';
  const negotiation=g.negotiation?`<div class="result-banner"><h3>截牌协商</h3><p>${esc(r.players[g.negotiation.seat].name)}请求${esc(r.players[g.negotiation.target].name)}收回上一手。</p>${g.negotiation.target===me?'<div class="phase-actions"><button class="primary" data-action="accept">同意收回</button><button class="secondary" data-action="reject">保留出牌</button></div>':'<p class="table-sub">等待对方选择。</p>'}</div>`:'';
  const controls=canPlay?`<div class="hand-controls"><div class="controls-left"><select class="control-select" id="play-type" aria-label="出牌方式">${special.map(a=>`<option value="${a}" ${playType===a?'selected':''}>${actions[a]}</option>`).join('')}</select>${!['landlord','basic'].includes(g.mode)&&g.hand.some(c=>c.rank===14&&c.suit==='S')?`<button class="text-button" data-action="declare-wild">逐张指定${Object.keys(wildcardMap).length?' · 已设定':''}</button><select class="control-select" id="wildcard" aria-label="黑桃A代替数值"><option value="">黑桃 A · 自动配牌</option>${Array.from({length:13},(_,i)=>i+3).map(n=>`<option value="${n}" ${wildcard==n?'selected':''}>黑桃 A 代替 ${ranks[n]}</option>`).join('')}</select>`:''}${playType==='urgent'?`<select class="control-select" id="gift-target" aria-label="赠牌对象"><option value="">赠牌给…</option>${r.players.map((p,s)=>s!==me&&!g.finished.includes(s)?`<option value="${s}" ${giftTarget==s?'selected':''}>${esc(p.name)}</option>`:'').join('')}</select>`:''}</div><div class="controls-right"><button class="text-button" data-action="deselect">清空</button><button class="secondary" data-action="hint">提示</button><button class="secondary" data-action="pass" ${g.turn!==me||!g.last||g.lastSeat===me?'disabled':''}>不出</button><button class="primary" data-action="play" ${selected.size===0||g.negotiation?'disabled':''}>${playType==='urgent'?'赠牌':'出牌'} <span>→</span></button></div></div><div class="selection-note" id="selection-note">${selected.size?'已选择 '+selected.size+' 张牌':'点选手牌；提示会选择一组合法出牌。'}${g.mode!=='landlord'?' · 上家出完后可使用特殊出法截牌。 <button class="text-button" data-action="negotiate">申请截牌协商</button>':''}</div>`:'<div class="selection-note">'+(g.phase==='over'?'本局手牌已封存。':'等待开局完成后出牌。')+'</div>';
  return roomHeading(r,true)+result+negotiation+`<div class="table-layout"><section class="board"><span class="board-chip">${r.rated?'真人积分对局':'AI 练习对局'} / ${r.code}</span><div class="board-watermark">纸 间</div>${seats}<div class="table-center">${center}</div></section><aside class="table-log"><div class="table-log-header"><span>牌桌动态</span><button class="text-button" data-action="rules">规则 ↗</button></div><div class="match-meta">${g.mode==='landlord'?`地主叫分 <b>${g.bid}</b>`:`本局主牌 <b>${ranks[g.main]}</b><br>${g.mode==='trio'?'三人个人争先':`我方 <b>${g.scores[me%2]}</b> · 对方 <b>${g.scores[1-me%2]}</b>`}`}<br>${r.rated?'计入积分与段位':'含 AI · 不计积分'}</div><div class="log-entries" aria-live="polite">${g.log.map(l=>`<div class="log-entry">${esc(l)}</div>`).join('')}</div></aside></div><section class="hand-area"><div class="hand-top"><strong>你的手牌 <span class="muted">/ ${g.hand.length} 张</span></strong><small>${g.mode==='landlord'?'按点数排列':'主牌大于 2，小于小王'}</small></div><div class="hand ${g.hand.length>23?'dense':''}">${g.hand.map(c=>card(c,canPlay,g)).join('')}</div>${controls}</section>`;
}
function showAuth(tab='login') {
  authTab=tab;
  showModal('auth',`<h2 class="modal-title">${tab==='login'?'欢迎回到牌桌。':'给自己留个座位。'}</h2><p class="modal-desc">一个昵称，认识一桌朋友。</p><div class="switch-tabs"><button data-action="auth-login" class="${tab==='login'?'active':''}">登录</button><button data-action="auth-register" class="${tab==='register'?'active':''}">注册</button></div><form class="form" id="auth-form"><label>玩家昵称<input name="name" required minlength="2" maxlength="18" autocomplete="username" placeholder="你的牌桌名字"></label><label>密码<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="${tab==='login'?'current-password':'new-password'}" placeholder="至少 8 个字符"></label><p class="form-error"></p><button class="primary full" type="submit">${tab==='login'?'回到俱乐部':'注册并入座'} →</button><p class="form-note">${tab==='register'?'初始 1000 积分。真人对局积累积分，AI 对局自在练习。':'登录后可恢复仍在进行的房间与对局。'}</p></form>`,'WELCOME TO THE CLUB');
}
function showCreate(mode='landlord') {
  createMode=mode;
  const single=screen==='single',capacity=mode==='landlord'||mode==='trio'?3:4,pref=state.preferences||{};
  showModal('create',`<h2 class="modal-title">${esc(names[mode])}</h2><p class="modal-desc">${single?'挑选对手，开始这一局练习。':'选好牌桌，邀请朋友入座。'}</p><form class="form" id="create-form"><label>AI 对手<select name="aiType"><option value="rules">规则 AI · 无需 API</option><option value="model" ${pref.configured?'':'disabled'}>模型 AI ${pref.configured?'· '+esc(pref.model):'· 请先在设置中配置 API'}</option></select></label>${single?`<p class="form-note">单人模式自动加入 ${capacity-1} 位 AI。</p>`:`<label>补充 AI 席位<select name="botCount">${Array.from({length:capacity},(_,n)=>`<option value="${n}">${n===0?'暂不加入 AI · 等待朋友':n+' 位 AI'}</option>`).join('')}</select></label>`}${['standard','trio'].includes(mode)?'<label class="checkbox"><input type="checkbox" name="advancedHui">启用「回」进阶版（同花色组合）</label><label class="checkbox"><input type="checkbox" name="advancedDead">启用「死压」进阶版（四张截牌权）</label>':''}${mode==='standard'?'<label class="checkbox"><input type="checkbox" name="dlc">Fieldlark 三周年 DLC（额外 40 张）</label>':''}<p class="form-note">${mode==='landlord'?'三人叫分抢地主，54 张经典规则。':mode==='trio'?'三人 86 张，独立争先。':'四人对座组队，主牌从 3 开始。'}<br>全真人对局计分，含 AI 对局不计分。</p><p class="form-error"></p><button class="primary full" type="submit">${single?'开始单人游戏':'创建房间'} →</button></form>`,'SET UP YOUR TABLE');
}

async function showLeaderboard(){requireUser(async()=>{showModal('leaderboard','<h2 class="modal-title">牌桌有名。</h2><p class="modal-desc">每一分，来自一场真人较量。</p><div class="empty">正在取来积分榜…</div>','THE LEADERBOARD');try{const d=await api('leaderboard');if(modalKind!=='leaderboard')return;$('#modal-content').innerHTML='<h2 class="modal-title">牌桌有名。</h2><p class="modal-desc">每一分，来自一场真人较量。</p>'+d.players.map((p,i)=>`<div class="leader-row"><span class="place">${String(i+1).padStart(2,'0')}</span><div>${esc(p.name)}${p.id===state.user.id?' · 你':''}<small>${p.rank} / ${p.wins} 胜 ${p.games} 场</small></div><span class="points">${p.points}</span></div>`).join('');}catch(e){toast(e.message);}});}
async function showProfile(){requireUser(async()=>{const u=state.user;showModal('profile',`<h2 class="modal-title">${esc(u.name)}</h2><p class="modal-desc">${u.rank} · 你的俱乐部档案</p><div class="profile-stats"><div><strong>${u.points}</strong><small>当前积分</small></div><div><strong>${u.games}</strong><small>真人对局</small></div><div><strong>${u.games?Math.round(u.wins/u.games*100):0}%</strong><small>获胜比例</small></div></div><div id="history"><p class="empty">正在加载战绩…</p></div><div class="divider"></div><button class="secondary full" data-action="logout">退出账号</button>`,'PLAYER ARCHIVE');try{const d=await api('history');if(modalKind!=='profile')return;$('#history').innerHTML=d.history.length?'<p class="eyebrow">RECENT MATCHES</p>'+d.history.map(h=>`<div class="leader-row"><span>${h.delta>0?'胜':'负'}</span><div>${names[h.mode]}<small>${new Date(h.created*1000).toLocaleString('zh-CN')}</small></div><span class="points">${h.delta>0?'+':''}${h.delta}</span></div>`).join(''):'<p class="empty">还没有真人对局记录。<br>邀请朋友一起开一局吧。</p>';}catch(e){toast(e.message);}});}
function showRules(){
 showModal('rules',`<h2 class="modal-title">几张牌，无穷变化。</h2><div class="switch-tabs"><button class="active" data-action="rules-classic">斗地主</button><button data-action="rules-special">4A4A4 2.4</button></div><div id="rule-text" class="rules"></div>`,'THE RULEBOOK');ruleText('classic');
}
function ruleText(type){
 $$('.switch-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.action==='rules-'+type));
 $('#rule-text').innerHTML=type==='classic'?`<h3>三人 · 一副牌</h3><p>每人 17 张，余下 3 张归地主。轮流叫 1–3 分，只能叫更高的分；叫 3 分立即成为地主。全部不叫时，本实现将最后叫分玩家设为 1 分地主。</p><h3>常见牌型</h3><p>单张、对子、三张、三带一、三带二、顺子（至少 5 张，不含 2 和王）、连对（至少 3 对）、飞机及带单/带对、四带二、四带两对。飞机的翅膀不能包含机身点数；单翼允许同点。</p><p>相同牌型、相同张数比大小。四张同点炸弹压普通牌；一小王加一大王为最大王炸。点数 3 最小，2 大于 A，大王最大。</p><h3>胜负与积分</h3><p>地主先出完则地主胜，任一农民先出完则两位农民胜。全真人牌桌胜方每人 +24，负方每人 −24，最低 0；有 AI 不结算积分。</p>`:`<h3>标准版与变体</h3><p>标准版四人 110 张：两副牌和两张急牌。对座组队，主牌初始为 3，点数大于 2、小于小王。顺子、连对、飞机不含主牌、2 和王。</p><p>三人 86 张：去掉两副牌的黑桃 3–K、两张小王和一张急牌，加入一张大王；每人独立争先。基础版四人 54 张：一副牌，三张起炸，仅额外支持勾、叉、4A4。</p><p>Fieldlark DLC 额外加入黑桃 A ×5、Delta A ×2、Delta 2–K 各2张、大小王各1张、急牌×7，共额外40张。可在创建标准房间时选择。</p><h3>开局</h3><p>可展示至少六张原生同点牌进行升变，多人升变取自然点数最大的牌为主。选择亮黑桃 3 的玩家争夺先手，多人亮牌通过猜拳决出一人；都不亮时房主先出。所有玩家确认后开始。下一局由上一局最先出完者先发牌、先出牌。</p><h3>特殊出牌</h3><table><tr><th>出法</th><th>条件与效果</th></tr><tr><td>叉</td><td>两张同点，管同点单张。</td></tr><tr><td>勾</td><td>一张同点，管叉出的两张牌。</td></tr><tr><td>点</td><td>一张同点，管非勾叉对子；点 2 或主直接获牌权。</td></tr><tr><td>压</td><td>一张 2、主或王，管点牌，直接获牌权。</td></tr><tr><td>死压</td><td>三张同点，管非勾叉对子，直接获牌权。进阶版可用四张同点截获死压牌权。</td></tr><tr><td>回</td><td>同花色单牌管小于 2 的非特殊单牌，每轮一次。进阶版允许相同牌型、张数且全组同花色；不比较点数。</td></tr><tr><td>黑桃 A</td><td>组合中可代替任意非王牌，不能单张当混子。自动配牌或手动指定替代点数。</td></tr><tr><td>急牌</td><td>选一张急牌和一张非急牌，赠给任一仍在场玩家；急牌弃掉。保留当前出牌机会。仅剩一张急牌自动末名。</td></tr></table><h3>炸弹与 4A4A4</h3><p>四炸 &lt; 双王 &lt; 五炸 &lt; 六炸 &lt; 三王 &lt; 七炸 &lt; 八炸 &lt; 四王 &lt; 九炸 &lt; 十炸 &lt; 基础 4A4A4 &lt; 更大 4A4A4。炸弹压普通及勾点叉。更多同点炸弹继续按张数排列。</p><p>标准 4A4A4 至少三张 4 和两张 A，4 的数量必须多于 A；先比总张数，相同张数再比 A 数量。基础版最低两张 4 和一张 A。</p><h3>抢牌权与协商</h3><p>正常情况下依次行动。若上一手玩家已出完，特殊出法可在原下一家行动之前截牌。原下一家已经出牌时，可选牌和特殊出法申请协商；对方同意才回退上一手并执行截牌。已有两人完成时不得协商。</p><h3>胜负、主牌与爆牌</h3><p>四人队伍的第二位成员先出完，该队获胜。每队加上自己全员出完时仍未完成的玩家数。下一局主牌由首位出完者所属队的累计分，从 3、4…K、A、2 循环对应。三人第一位出完者胜，以个人累计胜局循环决定下一局主牌。</p><p>手牌变动后若不超过 10 张，服务端自动公布剩余张数。“分”玩法停用。真人 4A4A4 胜方 +20、负方 −20，有 AI 不结算积分。认输直接结束本局，队友共同判负。</p><h3>段位</h3><p>800 以下纸牌学徒，800–1099 墨线新秀，1100–1399 银笔高手，1400–1799 黑金大师，1800–2399 牌桌宗师，2400 起无冕传奇。</p>`;
}
function $$(s){return [...document.querySelectorAll(s)];}
async function gameAction(action,extra={}){if(!state.room)return;await mutation('action',{action,revision:state.room.revision,...extra});}
function wildcardPayload(){
  const map=Object.fromEntries(Object.entries(wildcardMap).filter(([id])=>selected.has(id)));
  return Object.keys(map).length?map:(wildcard?Number(wildcard):undefined);
}
function showWildcard(){
  const wild=state.room?.game?.hand.filter(c=>selected.has(c.id)&&c.suit==='S'&&c.rank===14)||[];
  if(!wild.length||selected.size<2){toast('先选择至少两张牌，其中包含黑桃 A。');return;}
  showModal('wildcard',`<h2 class="modal-title">给黑桃 A 一个点数。</h2><p class="modal-desc">每张黑桃 A 可以独立代替非王牌。选择 A 表示保留原点数。</p><form class="form" id="wildcard-form">${wild.map((c,i)=>`<label>第 ${i+1} 张黑桃 A<select name="${esc(c.id)}">${Array.from({length:13},(_,i)=>i+3).map(n=>`<option value="${n}" ${n===(wildcardMap[c.id]||14)?'selected':''}>${ranks[n]}</option>`).join('')}</select></label>`).join('')}<button class="primary full" type="submit">确认配牌 →</button></form>`,'WILDCARD DECLARATION');
}
function selectionUpdate(){
 $$('.hand .card').forEach(b=>{b.classList.toggle('selected',selected.has(b.dataset.card));b.setAttribute('aria-pressed',selected.has(b.dataset.card));});
 const btn=$('[data-action="play"]');if(btn)btn.disabled=!selected.size||!!state.room?.game?.negotiation;
 const note=$('#selection-note');if(note){const text=note.firstChild;if(text?.nodeType===Node.TEXT_NODE)text.textContent=(selected.size?'已选择 '+selected.size+' 张牌':'点选手牌；提示会选择一组合法出牌。')+(state.room.game.mode==='landlord'?'':' · 上家出完后可使用特殊出法截牌。 ');}
}
document.addEventListener('click',async e=>{
 const c=e.target.closest('[data-card]');if(c){selected.has(c.dataset.card)?selected.delete(c.dataset.card):selected.add(c.dataset.card);selectionUpdate();return;}
 const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
 const action=b.dataset.action;
 try{
 switch(action){
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
 case 'bot':await mutation('bot');break;
 case 'remove':await mutation('remove',{seat:Number(b.dataset.seat)});break;
 case 'model-bot':await mutation('bot',{model:true});break;
 case 'clear-api':await mutation('model-settings',{clear:true});if(state.room)showSettingsModal();else{renderedKey='';render();}toast('API 配置已清除。');break;
 case 'start':selected.clear();playType='play';await mutation('start');break;
 case 'leave':await mutation('leave');if(!state.room)navigate('home');break;
 case 'resign':showModal('resign','<h2 class="modal-title">认输结束这一局？</h2><p class="modal-desc">本局立即结束。真人对局将结算负分；组队时你的队友也会判负。</p><div class="phase-actions"><button class="secondary" data-action="close">继续打牌</button><button class="primary" data-action="resign-confirm">确认认输</button></div>','END THIS MATCH');break;
 case 'resign-confirm':await mutation('resign');closeModal();break;
 case 'bid':await gameAction('bid',{value:Number(b.dataset.value)});break;
 case 'reveal':case 'confirm':case 'pass':case 'accept':case 'reject':await gameAction(action);break;
 case 'promote':await gameAction('promote',{rank:Number(b.dataset.rank)});break;
 case 'rps':await gameAction('rps',{value:b.dataset.value});break;
 case 'declare-wild':showWildcard();break;
 case 'deselect':selected.clear();selectionUpdate();break;
 case 'hint':{
   const result=await api('hint',{});hintMoves=result.moves;if(!hintMoves.length){toast('没有可以管住的牌，可以选择不出。');return;}
   const move=hintMoves[hintIndex++%hintMoves.length];selected=new Set(move.ids);playType=move.action;if(move.target!==undefined)giftTarget=String(move.target);wildcard='';wildcardMap={};renderedKey='';render();toast(move.label+' · 再点提示切换方案');break;
 }
 case 'play':{
   const args={ids:[...selected]};const wild=wildcardPayload();if(wild!==undefined)args.wildcard=wild;if(playType==='urgent'){if(giftTarget===''){toast('请选择赠牌对象。');return;}args.target=Number(giftTarget);}
   await gameAction(playType,args);break;
 }
 case 'negotiate':if(!['cross','hook','dot','press','dead','dead4'].includes(playType)){toast('先选择叉、勾、点、压或死压并选牌，再申请协商。');return;}await gameAction('negotiate',{special:playType,ids:[...selected],...(wildcardPayload()!==undefined?{wildcard:wildcardPayload()}:{})});break;
 }
 }catch(error){toast(error.message);}
});
document.addEventListener('change',e=>{
 if(e.target.id==='play-type'){playType=e.target.value;renderedKey='';render();}
 if(e.target.id==='wildcard'){wildcard=e.target.value;wildcardMap={};}
 if(e.target.id==='gift-target')giftTarget=e.target.value;
});
document.addEventListener('submit',async e=>{
 e.preventDefault();const f=e.target;
 if(f.id==='join-form'){const code=$('#join-code').value;requireUser(async()=>{await mutation('join',{code});});return;}
 const error=$('.form-error',f);const submit=$('button[type=submit]',f);if(submit)submit.disabled=true;
 try{
 if(f.id==='wildcard-form'){wildcardMap=Object.fromEntries([...new FormData(f)].map(([id,v])=>[id,Number(v)]));wildcard='';closeModal();renderedKey='';render();}
 if(f.id==='auth-form'){const data=Object.fromEntries(new FormData(f));await api(authTab,data);closeModal();renderedKey='';await sync();toast(authTab==='login'?'欢迎回到纸间。':'注册成功，牌桌在等你。');}
 if(f.id==='create-form'){await api('create',{mode:createMode,options:{advancedHui:f.elements.advancedHui?.checked||false,advancedDead:f.elements.advancedDead?.checked||false,dlc:f.elements.dlc?.checked||false}});const count=screen==='single'?(createMode==='landlord'||createMode==='trio'?2:3):Number(f.elements.botCount.value);for(let i=0;i<count;i++)await api('bot',{model:f.elements.aiType.value==='model'});if(screen==='single')await api('start',{});closeModal();await sync();}
 if(f.id==='api-settings-form'){await api('model-settings',Object.fromEntries(new FormData(f)));f.reset();await sync();if(state.room)showSettingsModal();toast('模型 API 已保存。');}
 if(f.id==='account-form'){await api('account',Object.fromEntries(new FormData(f)));await sync();if(state.room)showSettingsModal();toast('账号信息已更新。');}
 }catch(e){if(error)error.textContent=e.message;else toast(e.message);}finally{if(submit)submit.disabled=false;}
});
modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeModal();}});
modal.addEventListener('close',()=>{modalKind='';});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){clearTimeout(pollTimer);poll();}});
render();poll();
