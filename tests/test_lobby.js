'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('public/app.js','utf8');
function flow(screen){
  const context={screen};vm.createContext(context);
  return vm.runInContext(source.slice(source.indexOf('function flowScreen(){'),source.indexOf('function settingsScreen(){'))+'\nflowScreen();',context);
}
test('single and multiplayer flows expose an unlabeled room-number entrance',()=>{
  for(const screen of ['single','create']){
    const html=flow(screen);
    assert.ok(html.includes('id="join-form"'));
    assert.ok(html.includes('id="join-code"'));
    assert.ok(!html.includes('001255'));
    assert.ok(!html.includes('68686'));
    assert.ok(!html.includes('_alternate'));
  }
});
