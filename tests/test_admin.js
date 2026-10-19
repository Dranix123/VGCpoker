'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
async function fixture(status=200){
  const elements={},calls=[],location={href:''};
  const get=id=>elements[id]||(elements[id]={innerHTML:'',textContent:'',addEventListener(){},querySelectorAll(){this.bars=[...this.innerHTML.matchAll(/data-count="(\d+)"/g)].map(m=>({dataset:{count:m[1]},style:{}}));return this.bars;}});
  const data={now:1700000000,since:1699000000,dau:2,wau:3,mau:4,online:1,playing:1,active_games:1,running_games:2,rooms:3,users:5,new_users:1,historical_completed:7,
    totals:{started:10,today_started:2,completed:8,interrupted:1,average_seconds:42},ai:{requests:2,failures:1,seconds:3},
    days:[{day:'2026-10-19',dau:2,signups:1,started:2,single:1,multi:1}],
    modes:[{mode:'<script>',variant:'default',channel:'single',active:1,today_started:2,started:3,completed:2,interrupted:0,player_visits:3,average_seconds:61}]};
  const sandbox={document:{querySelector:get},location,setInterval(){},fetch:async(path)=>{calls.push(path);return {status,ok:status===200,json:async()=>data};}};
  vm.createContext(sandbox);vm.runInContext(fs.readFileSync('admin/app.js','utf8'),sandbox);
  await new Promise(resolve=>setImmediate(resolve));return {elements,calls,location};
}
test('admin renders counts, safe labels and chart heights without recording player activity',async()=>{
  const f=await fixture();assert.deepEqual(f.calls,['/api/stats']);
  assert.ok(f.elements['#overview'].innerHTML.includes('42 秒'));
  assert.ok(f.elements['#modes'].innerHTML.includes('&lt;script&gt;'));
  assert.ok(!f.elements['#modes'].innerHTML.includes('<script>'));
  assert.equal(f.elements['#trend'].bars[0].style.height,'100%');
  assert.ok(f.elements['#notes'].textContent.includes('历史已完成战绩'));
});
test('admin redirects an expired login and displays service errors',async()=>{
  const expired=await fixture(401);assert.equal(expired.location.href,'/');
  const failed=await fixture(500);assert.ok(failed.elements['#error'].textContent.includes('无法加载'));
});
