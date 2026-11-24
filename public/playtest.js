'use strict';

const playtestStatuses = {
  queued:'排队中', running:'进行中', cancelling:'正在停止', cancelled:'已停止',
  completed:'已完成', failed:'失败', step_limit:'达到行动上限', interrupted:'已中断'
};
const playtestActive = run => ['queued','running','cancelling'].includes(run?.status);

function mountPlaytest(root){
  if(!root||root.dataset.mounted)return;
  root.dataset.mounted='true';
  root.innerHTML=`<div class="playtest-grid">
    <div class="playtest-controls">
      <form class="form playtest-card" data-playtest-key>
        <h3>DeepSeek API</h3>
        <p data-key-status role="status"></p>
        <label>API Key<input name="key" type="password" maxlength="512" autocomplete="off" required></label>
        <div class="playtest-buttons"><button class="secondary" type="submit">保存密钥</button><button class="text-button" type="button" data-key-clear>清除</button></div>
        <p class="form-error" role="alert"></p>
      </form>
      <form class="form playtest-card" data-playtest-start hidden>
        <h3>新任务</h3>
        <div class="playtest-fields">
          <label>玩法<select name="mode">${Object.entries(names).map(([value,label])=>`<option value="${value}">${label}</option>`).join('')}</select></label>
          <label>玩家<select name="driver"><option value="rules">规则 AI</option><option value="deepseek">DeepSeek</option></select></label>
        </div>
        <div class="playtest-fields" data-model-options hidden>
          <label>模型<select name="model"></select></label>
          <label class="checkbox playtest-thinking"><input name="thinking" type="checkbox">启用思考</label>
        </div>
        <div class="playtest-fields" data-playtest-skills></div>
        <label class="checkbox" data-first-out><input name="firstOut" type="checkbox">首位走完即结算</label>
        <div class="playtest-fields">
          <label>局数<input name="games" type="number" min="1" max="30" value="1" required></label>
          <label>每局行动上限<input name="maxSteps" type="number" min="1" max="5000" value="600" required></label>
          <label data-call-limit hidden>模型调用上限<input name="maxModelCalls" type="number" min="1" max="10000" value="250" required></label>
        </div>
        <button class="primary" type="submit">开始测试</button>
        <p class="form-error" role="alert"></p>
      </form>
    </div>
    <div class="playtest-controls">
      <section class="playtest-card"><h3>任务进度</h3><div data-playtest-progress>正在加载…</div></section>
      <section class="playtest-card"><h3>最近任务</h3><div data-playtest-history></div></section>
    </div>
  </div>`;
  const keyForm=$('[data-playtest-key]',root), launchForm=$('[data-playtest-start]',root);
  const progress=$('[data-playtest-progress]',root), history=$('[data-playtest-history]',root);
  let runs=[], current=null, configured=false, timer, stopping=false, starting=false;

  function updateOptions(){
    const conveyor=launchForm.elements.mode.value==='conveyor';
    const deepseek=launchForm.elements.driver.value==='deepseek';
    $('[data-playtest-skills]',root).hidden=!conveyor;
    $('[data-first-out]',root).hidden=!conveyor;
    $('[data-model-options]',root).hidden=!deepseek;
    $('[data-call-limit]',root).hidden=!deepseek;
    $('[data-key-status]',root).textContent=configured?'已保存 · 本次服务运行期间有效':'尚未保存';
    $('[data-key-clear]',root).disabled=!configured;
    $('button[type="submit"]',launchForm).disabled=starting||runs.some(playtestActive)||deepseek&&!configured;
    const error=$('.form-error',launchForm);
    if(deepseek&&!configured&&!error.textContent)error.textContent='请先保存你自己的 DeepSeek API Key。';
    else if((!deepseek||configured)&&error.textContent==='请先保存你自己的 DeepSeek API Key。')error.textContent='';
  }

  function draw(){
    const task=runs.find(run=>run.id===current);
    if(!task){
      progress.innerHTML='<p class="muted">暂无任务</p>';
    }else{
      const status=playtestStatuses[task.status]||task.status;
      const count=task.config?.games??1;
      const completed=task.matches?.filter(m=>m.status==='completed').length??0;
      const detail=task.currentMatch?`第 ${task.currentMatch} 局 · 已执行 ${task.currentStep||0} 步`:'';
      const matches=[...(task.matches||[])];
      if(['failed','interrupted'].includes(task.status)&&task.currentMatch&&!matches.some(m=>m.match===task.currentMatch)){
        matches.push({match:task.currentMatch,status:task.status,steps:task.currentStep||0});
      }
      const results=matches.map(m=>`<li><span>第 ${m.match} 局 · ${m.winner?.length?m.winner.map(seat=>(seat+1)+' 号').join('、')+'获胜':esc(playtestStatuses[m.status]||m.status)} · ${m.steps} 步</span><button class="secondary" type="button" data-replay-match="${m.match}" aria-label="回放第 ${m.match} 局">回放</button></li>`).join('');
      progress.innerHTML=`<div class="playtest-task-title"><strong>${esc(names[task.config?.mode]||task.config?.mode)}</strong><span>${esc(status)}</span></div>
        <progress value="${completed}" max="${count}" aria-label="已完成局数"></progress>
        <p>${completed} / ${count} 局${detail?' · '+detail:''}</p>
        <p class="muted">${task.model?esc(task.model)+' · '+(task.thinking?'思考开启':'思考关闭'):'规则 AI'} · 请求 ${task.calls||0} 次 · 回退 ${task.fallbacks||0} 次${task.tokens?.total_tokens?' · '+task.tokens.total_tokens+' tokens':''}</p>
        ${task.modelDisabledReason?'<p class="form-error">DeepSeek 授权失败，余下行动使用规则 AI。</p>':''}
        ${task.modelBudgetReached?'<p class="muted">已用完指定的模型调用次数。</p>':''}
        ${task.error?`<p class="form-error">${esc(task.error.reason||task.error.type)}</p>`:''}
        ${results?`<ul class="playtest-results">${results}</ul>`:''}
        <div class="playtest-buttons">
          ${!playtestActive(task)?`<a class="secondary" href="/api/playtest/runs/${esc(task.id)}/log" download>下载日志</a>`:''}
          ${playtestActive(task)?`<button class="text-button" type="button" data-stop-playtest ${stopping||task.status==='cancelling'?'disabled':''}>停止测试</button>`:''}
        </div>`;
    }
    history.innerHTML=runs.length?runs.map(run=>`<button class="playtest-history-item" type="button" data-playtest-run="${esc(run.id)}" aria-pressed="${run.id===current}">
      <span>${esc(names[run.config?.mode]||run.config?.mode)} <small>${esc(run.id.slice(0,8))}</small></span><span>${esc(playtestStatuses[run.status]||run.status)}</span></button>`).join(''):'<p class="muted">暂无记录</p>';
    updateOptions();
  }

  async function refresh(){
    clearTimeout(timer);
    if(!root.isConnected)return;
    try{
      const data=await api('playtest');
      if(!root.isConnected)return;
      configured=data.configured;
      runs=data.runs;
      if(!current)current=(runs.find(playtestActive)||runs[0])?.id||null;
      const model=launchForm.elements.model;
      if(!model.options.length){
        const labels={'deepseek-flash':'DeepSeek Flash','deepseek-v4-pro':'DeepSeek Pro'};
        model.innerHTML=data.models.map(name=>`<option value="${esc(name)}">${esc(labels[name]||name)}</option>`).join('');
        launchForm.elements.driver.value=configured?'deepseek':'rules';
      }
      launchForm.hidden=false;
      draw();
    }catch(error){
      if(root.isConnected)progress.textContent=error.message;
    }
    if(root.isConnected&&runs.some(playtestActive))timer=setTimeout(refresh,1200);
  }

  const skills=state.features?.conveyorSkills||[];
  $('[data-playtest-skills]',root).innerHTML=Array.from({length:4},(_,i)=>`<label>${i+1} 号技能
    <select name="skill${i}"><option value="">随机选择</option>${Object.entries(conveyorGroups).map(([group,title])=>`<optgroup label="${esc(title)}">${skills.filter(s=>s.group===Number(group)).map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</optgroup>`).join('')}</select></label>`).join('');
  launchForm.addEventListener('change',updateOptions);
  root.addEventListener('submit',async event=>{
    event.preventDefault();
    event.stopPropagation();
    const form=event.target;
    const error=$('.form-error',form), submit=$('button[type="submit"]',form);
    if(!error||submit.disabled)return;
    error.textContent='';
    submit.disabled=true;
    try{
      if(form===keyForm){
        const result=await api('playtest/credential',{key:form.elements.key.value});
        form.reset();
        configured=result.configured;
        launchForm.elements.driver.value='deepseek';
      }else if(form===launchForm){
        starting=true;
        const fields=form.elements;
        const config={mode:fields.mode.value,driver:fields.driver.value,games:Number(fields.games.value),
          maxSteps:Number(fields.maxSteps.value),maxModelCalls:Number(fields.maxModelCalls.value),
          model:fields.model.value,thinking:fields.thinking.checked};
        if(config.mode==='conveyor'){
          config.skills=Array.from({length:4},(_,i)=>fields['skill'+i].value||null);
          config.options={firstOutEndsRound:fields.firstOut.checked};
        }
        const result=await api('playtest/runs',config);
        current=result.id;
        progress.textContent='正在启动任务…';
        await refresh();
        if(root.isConnected)progress.scrollIntoView({block:'nearest'});
      }
    }catch(err){error.textContent=err.message;}
    finally{starting=false;submit.disabled=false;updateOptions();}
  });
  root.addEventListener('click',async event=>{
    const run=event.target.closest('[data-playtest-run]');
    if(run){current=run.dataset.playtestRun;draw();return;}
    const replay=event.target.closest('[data-replay-match]');
    if(replay){openPlaytestReplay(current,replay.dataset.replayMatch);return;}
    if(event.target.closest('[data-key-clear]')){
      try{configured=(await api('playtest/credential',{clear:true})).configured;updateOptions();}
      catch(err){$('.form-error',keyForm).textContent=err.message;}
    }
    if(event.target.closest('[data-stop-playtest]')&&!stopping){
      stopping=true;
      draw();
      try{await api('playtest/runs/'+current+'/cancel',{});await refresh();}
      catch(err){toast(err.message);}
      finally{stopping=false;draw();}
    }
  });
  refresh();
}

function openPlaytestReplay(run, match){
  const dialog=$('#playtest-replay-dialog');
  const endpoint='playtest/runs/'+run+'/matches/'+match;
  dialog.innerHTML=`
    <header class="replay-header"><h2 id="replay-title">第 ${esc(match)} 局回放</h2><button type="button" class="icon-button" data-replay-close aria-label="关闭回放" autofocus>×</button></header>
    <div class="replay-stage" aria-label="回放牌桌"></div>
    <div class="replay-footer">
      <p class="replay-status" role="status">正在加载…</p>
      <input type="range" min="0" max="0" value="0" aria-label="回放进度" disabled>
      <nav aria-label="回放控制">
        <button type="button" class="secondary" data-replay-prev disabled>上一步</button>
        <button type="button" class="primary" data-replay-toggle disabled>播放</button>
        <button type="button" class="secondary" data-replay-next disabled>下一步</button>
        <span class="replay-counter"></span>
      </nav>
    </div>`;
  const stage=$('.replay-stage',dialog), status=$('.replay-status',dialog), counter=$('.replay-counter',dialog);
  const slider=$('input',dialog), prev=$('[data-replay-prev]',dialog), next=$('[data-replay-next]',dialog), toggle=$('[data-replay-toggle]',dialog);
  let info, current=0, playing=false, timer, request=0, closed=false;

  function stop(){
    playing=false;
    clearTimeout(timer);
    toggle.textContent='播放';
  }

  function paint(frame, index){
    current=index;
    const room={...info.room,game:frame.game};
    const history=$('.table-archive',stage);
    const historyOpen=history?.open;
    const logScroll=$('.log-entries',stage)?.scrollTop;
    stage.innerHTML=table(room,frame.game);
    const archive=$('.table-archive',stage);
    if(archive&&historyOpen!==undefined)archive.open=historyOpen;
    const log=$('.log-entries',stage);
    if(log)log.scrollTop=playing?log.scrollHeight:logScroll??log.scrollHeight;
    const last=index===info.frames-1;
    const winner=(frame.game.winner||[]).map(seat=>room.players[seat].name).join('、');
    status.textContent=[
      last&&winner?winner+'获胜':index===0?'开局':frame.message||room.players[frame.seat]?.name,
      last&&info.status!=='completed'?playtestStatuses[info.status]:'',
      frame.legacy?'早期记录依据日志还原':''
    ].filter(Boolean).join(' · ');
    counter.textContent=index+' / '+(info.frames-1);
    slider.value=index;
    slider.setAttribute('aria-valuetext','第 '+index+' 步，共 '+(info.frames-1)+' 步');
    prev.disabled=index===0;
    next.disabled=last;
    if(last)stop();
    if(playing)timer=setTimeout(()=>seek(current+1),850);
  }

  async function seek(index){
    clearTimeout(timer);
    const version=++request;
    try{
      const frame=index===0?info.first:await api(endpoint+'/frames/'+index);
      if(!closed&&version===request)paint(frame,index);
    }catch(error){
      if(!closed&&version===request){stop();slider.value=current;status.textContent=error.message;}
    }
  }

  $('[data-replay-close]',dialog).onclick=()=>dialog.close();
  prev.onclick=()=>{stop();seek(current-1);};
  next.onclick=()=>{stop();seek(current+1);};
  slider.oninput=()=>{stop();request++;timer=setTimeout(()=>seek(Number(slider.value)),80);};
  toggle.onclick=()=>{
    if(playing){stop();request++;return;}
    playing=true;
    toggle.textContent='暂停';
    seek(current===info.frames-1?0:current+1);
  };
  stage.onclick=event=>{
    const skill=conveyorSkill(event.target.closest('[data-skill]')?.dataset.skill);
    if(!skill)return;
    stop();
    $('.replay-skill',stage)?.remove();
    const detail=document.createElement('aside');
    detail.className='replay-skill';
    detail.innerHTML=`<strong>${esc(skill.name)}</strong><p>${esc(skill.text)}</p>`;
    stage.prepend(detail);
  };
  dialog.onclick=event=>event.stopPropagation();
  dialog.addEventListener('close',()=>{closed=true;stop();},{once:true});
  dialog.showModal();
  api(endpoint).then(data=>{
    if(closed)return;
    info=data;
    $('#replay-title',dialog).textContent=names[info.room.mode]+' · 第 '+match+' 局回放';
    slider.max=info.frames-1;
    slider.disabled=toggle.disabled=info.frames<2;
    paint(info.first,0);
  }).catch(error=>{if(!closed)status.textContent=error.message;});
}
