const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync('public/splashes.js','utf8'),ctx);
test('splash category weights are exact, including four equally likely treasures',()=>{
 const counts=[0,0,0,0,0];
 for(let n=0;n<1000;n++){ctx.roll=(n+.5)/1000;const index=vm.runInContext('splashGroups.findIndex(([,lines])=>lines.split("\\n").includes(chooseSplash((()=>{let i=0;return ()=>i++?0:roll;})())))',ctx);counts[index]++;}
 assert.deepEqual(counts,[550,350,50,49,1]);
 assert.equal(vm.runInContext('splashGroups[4][1].split("\\n").length',ctx),4);
});
