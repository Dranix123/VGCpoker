'use strict';
const gameAudio = (() => {
  const defaults = {effects: .55, music: .4, voice: .7};
  let volumes = {...defaults}, context, unlocked = false, manifest = {music:{}, effects:{}, voices:{}}, previous, initialCounts = [], musicMode = 'menu', fadeFrame;
  const tracks = {}, mixes = {menu:1, table:0, tension:0}, buffers = new Map();
  try { const saved = JSON.parse(localStorage.getItem('paper-poker-audio')); for (const k in defaults) if (Number.isFinite(saved?.[k])) volumes[k] = Math.max(0, Math.min(1, saved[k])); } catch {}
  const ready = fetch('/audio/manifest.json', {cache:'no-store'}).then(r=>r.json()).then(data=>{
    manifest=data;
    for(const name of ['menu','table','tension']) if(manifest.music[name]) {
      const track = new Audio(manifest.music[name]); track.loop=true; track.preload='auto'; track.volume=0; tracks[name]=track;
      track.addEventListener('error',()=>{track.pause();delete tracks[name];const mode=musicMode;musicMode='';setMusic(mode);});
    }
    const mode=musicMode;musicMode='';setMusic(mode);
  }).catch(()=>{});
  function applyVolumes() {for(const [name,track] of Object.entries(tracks)) track.volume=volumes.music*mixes[name];}
  function startMusic() {
    if(!unlocked || document.hidden) return;
    const active = musicMode==='menu'?['menu']:['table','tension'];
    // Keep both match tracks running, including the silent one, on one timeline.
    for(const name of active) if(tracks[name]?.paused) tracks[name].play().catch(()=>{});
    for(const name of Object.keys(tracks)) if(!active.includes(name)) tracks[name].pause();
    applyVolumes();
  }
  function setMusic(mode, reset=false) {
    if(mode===musicMode&&!reset)return;
    const enteringMatch=musicMode==='menu'&&mode!=='menu'; musicMode=mode;
    if(reset||enteringMatch) for(const name of ['table','tension']) if(tracks[name]) tracks[name].currentTime=0;
    if(mode==='tension' && tracks.table && tracks.tension) {
      const t=tracks.table.currentTime, duration=tracks.tension.duration;
      tracks.tension.currentTime=Number.isFinite(duration)&&duration>0?t%duration:t;
    }
    // Without a tension asset, retain normal match music instead of fading to silence.
    const effective=mode==='tension'&&!tracks.tension?'table':mode;
    const target={menu:effective==='menu'?1:0,table:effective==='table'?1:0,tension:effective==='tension'?1:0};
    cancelAnimationFrame(fadeFrame);
    const from={...mixes}, started=performance.now();
    function fade(now){const p=Math.min(1,(now-started)/1500);for(const k in mixes)mixes[k]=from[k]+(target[k]-from[k])*p;applyVolumes();if(p<1)fadeFrame=requestAnimationFrame(fade);}
    fadeFrame=requestAnimationFrame(fade); startMusic();
  }
  function unlock() {
    if(!context){const AudioContext=window.AudioContext||window.webkitAudioContext;if(AudioContext)context=new AudioContext();}
    context?.resume().catch(()=>{});
    if(!unlocked&&context){const silent=context.createBufferSource();silent.buffer=context.createBuffer(1,1,context.sampleRate);silent.connect(context.destination);silent.start();}
    unlocked=true;ready.then(()=>{startMusic();processAnnouncement(latestRoom);});
  }
  function synth(name) {
    if(!context||!volumes.effects||document.hidden)return;
    const now=context.currentTime, gain=context.createGain();gain.connect(context.destination);
    const sequences={click:[[700,0,.035]],play:[[180,0,.07],[250,.04,.08]],deal:Array.from({length:8},(_,i)=>[900-i*55,i*.09,.045]),win:[[392,0,.14],[494,.15,.14],[587,.3,.14],[784,.46,.35]],lose:[[330,0,.2],[294,.22,.2],[220,.44,.4]]};
    gain.gain.value=volumes.effects*.13;
    for(const [frequency,delay,duration] of sequences[name]||[]) {
      const tone=context.createOscillator(), envelope=context.createGain();tone.type='triangle';tone.frequency.value=frequency;
      envelope.gain.setValueAtTime(0,now+delay);envelope.gain.linearRampToValueAtTime(1,now+delay+.008);envelope.gain.exponentialRampToValueAtTime(.001,now+delay+duration);
      tone.connect(envelope);envelope.connect(gain);tone.start(now+delay);tone.stop(now+delay+duration);
    }
    if(name==='play'||name==='deal') {
      const length=Math.floor(context.sampleRate*.08), noise=context.createBuffer(1,length,context.sampleRate), data=noise.getChannelData(0);
      for(let i=0;i<length;i++)data[i]=(Math.random()*2-1)*(1-i/length);
      const source=context.createBufferSource(), filter=context.createBiquadFilter();source.buffer=noise;filter.type='highpass';filter.frequency.value=1600;source.connect(filter);filter.connect(gain);source.start();
    }
    setTimeout(()=>gain.disconnect(),1300);
    const duration=Math.max(...(sequences[name]||[]).map(([,delay,length])=>delay+length),0);
    return new Promise(resolve=>setTimeout(resolve,duration*1000+40));
  }
  function audioBuffer(path) {
    if(!buffers.has(path))buffers.set(path,fetch(path).then(r=>{if(!r.ok)throw Error();return r.arrayBuffer();}).then(b=>context.decodeAudioData(b)));
    return buffers.get(path);
  }
  async function effect(name) {
    if(!unlocked||document.hidden||!volumes.effects)return;
    const path=manifest.effects[name];if(!path)return synth(name);
    try {
      const buffer=await audioBuffer(path);if(!volumes.effects||document.hidden)return;
      const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffer;gain.gain.value=volumes.effects;source.connect(gain);gain.connect(context.destination);await new Promise(resolve=>{source.onended=()=>{gain.disconnect();resolve();};source.start();});
    } catch {return synth(name);}
  }
  let voiceSource, voiceGain, voiceRequest=0, voiceResolve;
  function stopVoice(){voiceRequest++;voiceSource?.stop();voiceSource=null;window.speechSynthesis?.cancel();voiceResolve?.();voiceResolve=null;}
  async function speak(text, key=text) {
    if(!unlocked||document.hidden||!volumes.voice)return;
    stopVoice();const request=voiceRequest, path=manifest.voices[key];
    if(!path||!context)return speech(text);
    try {
      const buffer=await audioBuffer(path);
      if(request!==voiceRequest||!volumes.voice||document.hidden)return;
      const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffer;gain.gain.value=volumes.voice;
      source.connect(gain);gain.connect(context.destination);voiceSource=source;voiceGain=gain;
      await new Promise(resolve=>{voiceResolve=resolve;source.onended=()=>{gain.disconnect();if(voiceSource===source)voiceSource=null;resolve();};source.start();});
    } catch {if(request===voiceRequest)return speech(text);}
  }
  function speech(text) {
    if(!window.speechSynthesis||!volumes.voice||document.hidden)return;
    const line=new SpeechSynthesisUtterance(text);line.lang='zh-CN';line.volume=volumes.voice;line.rate=1.15;
    const chinese=window.speechSynthesis.getVoices().find(v=>v.lang.startsWith('zh'));if(chinese)line.voice=chinese;
    return new Promise(resolve=>{voiceResolve=resolve;line.onend=resolve;line.onerror=resolve;window.speechSynthesis.speak(line);setTimeout(resolve,10000);});
  }
  function observe(room) {
    latestRoom=room;
    const g=room?.game, match=g?`${room.code}/${room.matchId}`:'';
    if(!g){previous=null;initialCounts=[];setMusic('menu');return;}
    const fresh=previous?.match!==match;
    if(fresh){initialCounts=(g.initialCounts||g.counts).slice();if(g.phase!=='over'){if(!room.audioEvent)effect('deal');document.body.classList.add('dealing');setTimeout(()=>document.body.classList.remove('dealing'),1100);}}
    if(!fresh&&!room.audioEvent) {
      const changed=(g.seatPlays||[]).map((play,seat)=>({play,seat})).filter(({play,seat})=>play&&JSON.stringify(play)!==previous.plays[seat]);
      changed.sort((a,b)=>a.play.order-b.play.order);
      for(const {play} of changed){if(play.passed)speak('不出','pass');else {effect('play');const rank=({11:'勾',12:'圈',13:'凯',14:'尖',15:'二',16:'小王',17:'大王'})[play.ranks[0]]||play.ranks[0];speak(play.kind==='单张'?String(rank):play.kind==='对子'?'一对'+rank:play.kind,['单张','对子'].includes(play.kind)?play.kind+'-'+play.ranks[0]:play.kind);}}
      if(g.phase==='over'&&previous.phase!=='over'&&!room.spectator)effect(g.winner.includes(room.seat)?'win':'lose');
    }
    // Once the match reaches the endgame, keep tension music until settlement.
    const tense=!fresh&&previous.tense||(g.conveyor?g.conveyor.actors.some(a=>a.initialCount>0&&a.count<=a.initialCount*.3):g.counts.some((n,s)=>initialCounts[s]>0&&n<=initialCounts[s]*.3));
    setMusic(g.phase==='over'?'menu':tense?'tension':'table',fresh);
    previous={match,phase:g.phase,tense,plays:(g.seatPlays||[]).map(p=>JSON.stringify(p))};
    processAnnouncement(room);
  }
  function setVolume(category,value) {
    if(!(category in volumes))return;
    volumes[category]=Math.max(0,Math.min(1,Number(value)));try{localStorage.setItem('paper-poker-audio',JSON.stringify(volumes));}catch{}
    applyVolumes();if(category==='voice'){if(voiceGain)voiceGain.gain.value=volumes.voice;if(!volumes.voice)stopVoice();}
  }
  let latestRoom, playingEvent='', completedEvent='', eventJob=false;
  async function processAnnouncement(room){
    const event=room?.audioEvent;
    if(!event||!room.game||!unlocked||document.hidden||eventJob)return;
    const key=`${room.code}/${room.matchId}/${event.id}`;
    if(key===completedEvent)return;
    eventJob=true;
    try{
      if(key!==playingEvent){
        playingEvent=key;
        for(const item of event.items){
          if(document.hidden){playingEvent='';return;}
          if(item.effect)await effect(item.effect==='result'?(room.game.winner.includes(room.seat)?'win':'lose'):item.effect);
          if(item.text)await speak(item.text, 'conveyor-action');
          if(item.voice){const rank=Number(item.voice.split('-')[1]), letter={11:'勾',12:'圈',13:'凯',14:'尖',15:'二',16:'小王',17:'大王'}[rank]||rank;const text=item.voice.startsWith('单张-')?String(letter):item.voice.startsWith('对子-')?'一对'+letter:manifest.voiceText?.[item.voice]||(item.voice==='pass'?'不出':item.voice);await speak(text,item.voice);}
        }
      }
      if(document.hidden){playingEvent='';return;}
      const response=await fetch('/api/audio-ack',{method:'POST',headers:{'Content-Type':'application/json','X-Poker-Audio':'1'},body:JSON.stringify({event:event.id})});
      if(response.ok)completedEvent=key;
    }catch {}finally{eventJob=false;}
  }
  document.addEventListener('pointerdown',unlock,{passive:true});document.addEventListener('touchend',unlock,{passive:true});document.addEventListener('keydown',unlock);
  document.addEventListener('click',e=>{if(e.target.closest('button:not(:disabled)')){unlock();effect('click');}},true);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){for(const track of Object.values(tracks))track.pause();stopVoice();}else startMusic();});
  return {volumes, setVolume, effect, speak:(...args)=>eventJob?undefined:speak(...args), observe};
})();
