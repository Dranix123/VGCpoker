'use strict';
const $=s=>document.querySelector(s);
const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=v=>Number(v||0).toLocaleString('zh-CN');
const duration=v=>{if(v==null)return '—';const seconds=Math.round(v);return seconds<60?seconds+' 秒':Math.floor(seconds/60)+' 分 '+seconds%60+' 秒';};
const date=v=>new Date(v*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
let loading=false;
async function refresh(){
 if(loading)return;loading=true;
 try{
  const response=await fetch('/api/stats',{cache:'no-store'});
  if(response.status===401){location.href='/';return;}
  if(!response.ok)throw Error('统计暂时无法加载。');
  const d=await response.json(),t=d.totals,closed=t.completed+t.interrupted;
  const metrics=[['今日日活',d.dau,`近 7 天 ${number(d.wau)} · 近 30 天 ${number(d.mau)}`],['在线用户',d.online,`正在牌局中 ${number(d.playing)}`],['活跃牌局',d.active_games,`未结束 ${number(d.running_games)} · 房间 ${number(d.rooms)}`],['今日开局',t.today_started,`累计开局 ${number(t.started)}`],['注册账号',d.users,`今日新增 ${number(d.new_users)}`],['累计完成',t.completed,`认输 ${number(t.resigned)} · 中断 ${number(t.interrupted)} · 已关闭牌局完成率 ${closed?Math.round(t.completed/closed*100):0}%`],['平均对局时长',duration(t.average_seconds),'仅统计完成的对局'],['今日模型调用',d.ai.requests,`失败 ${number(d.ai.failures)} · 失败率 ${d.ai.requests?Math.round(d.ai.failures/d.ai.requests*100):0}% · 均耗时 ${d.ai.requests?(d.ai.seconds/d.ai.requests).toFixed(1):0}s`]];
  $('#overview').innerHTML=metrics.map(([label,value,note])=>`<div class="metric"><span>${escape(label)}</span><strong>${typeof value==='number'?number(value):escape(value)}</strong><small>${escape(note)}</small></div>`).join('');
  const maximum=Math.max(1,...d.days.flatMap(x=>[x.dau,x.single,x.multi]));
  $('#trend').innerHTML=d.days.map((x,i)=>`<div class="day" title="${escape(x.day)} 日活 ${x.dau} / 单人 ${x.single} / 联机 ${x.multi}">${[['users',x.dau],['single',x.single],['multi',x.multi]].map(([kind,value])=>`<div class="bar ${kind}" data-count="${value}"></div>`).join('')}${i%5===0||i===29?`<label>${x.day.slice(5)}</label>`:''}</div>`).join('');
  $('#trend').querySelectorAll('.bar').forEach(bar=>{bar.style.height=Number(bar.dataset.count)/maximum*100+'%';});
  const names={conveyor:'传送带',landlord:'斗地主',basic:'4A4 基础',standard:'4A4A4 标准',trio:'4A4A4 三人'};
  $('#modes').innerHTML=d.modes.map(r=>`<tr><td>${names[r.mode]||escape(r.mode)}${r.variant==='alternate'?' · 特殊规则':r.variant==='dlc'?' · DLC':''}</td><td>${r.channel==='single'?'单人':'联机'}</td>${[r.active,r.today_started,r.started,r.completed,r.interrupted,r.player_visits].map(v=>`<td>${number(v)}</td>`).join('')}<td>${duration(r.average_seconds)}</td></tr>`).join('');
  $('#daily').innerHTML=[...d.days].reverse().map(r=>`<tr><td>${r.day}</td>${[r.dau,r.signups,r.started,r.single,r.multi].map(v=>`<td>${number(v)}</td>`).join('')}</tr>`).join('');
  $('#updated').textContent='更新于 '+date(d.now);
  $('#notes').textContent=`开局、时长、日活与模型调用从 ${date(d.since)} 开始记录，累计开局不等于完成局数。此前未分类的历史已完成战绩 ${number(d.historical_completed)} 局，单独保留。重启或主动离开造成的未完成对局计为中断；后台无玩家身份、手牌或 API 密钥信息。`;
  $('#error').textContent='';
 }catch(error){$('#error').textContent=error.message;}finally{loading=false;}
}
$('#refresh').addEventListener('click',refresh);refresh();setInterval(refresh,10000);
