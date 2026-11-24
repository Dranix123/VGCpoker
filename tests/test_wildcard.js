'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('public/app.js','utf8');
function payload(ranks,map={}){
 const hand=ranks.map((rank,i)=>({id:String(i),rank,suit:rank===14?'S':'H'}));
 const context={state:{room:{game:{hand}}},selected:new Set(hand.map(c=>c.id)),wildcardMap:map};
 vm.createContext(context);
 return vm.runInContext(source.slice(source.indexOf('function wildRank('),source.indexOf('function urgentSelected('))+'\nwildcardPayload();',context);
}
test('previous spade ace rank does not leak into natural airplane, pair run or three jokers',()=>{
 for(const ranks of [[11,11,11,12,12,12,8,10],[4,4,5,5,6,6],[16,16,17]])assert.equal(payload(ranks,{'discarded-ace':5}),undefined);
});
test('declarations include only selected spade aces and preserve valid rank/suit or urgent assignment',()=>{
 assert.equal(JSON.stringify(payload([5,5,5,14],{'3':5})),JSON.stringify({'3':5}));
 const map=payload([5,5,5,14],{'3':{rank:5,suit:'D'},'0':9,'stale':8});
 assert.equal(JSON.stringify(map),JSON.stringify({'3':{rank:5,suit:'D'}}));
 assert.equal(payload([14],{'0':{rank:14,suit:'D'}}),undefined);
 assert.equal(payload([14],{'0':5}),undefined);
 assert.equal(payload([14],{'0':{rank:18,suit:'D'}}),18);
 assert.equal(JSON.stringify(payload([14,8],{'0':18})),JSON.stringify({'0':18}));
 assert.equal(payload([6,7],{'0':5}),undefined);
});
