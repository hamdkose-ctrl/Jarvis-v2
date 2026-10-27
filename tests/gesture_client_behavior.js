'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const src=fs.readFileSync(path.join(__dirname,'../webui/gesture-client.js'),'utf8');

function make(){
  const calls=[];
  const context={
    api:async(...args)=>{calls.push(args);return {intent:'stop'};},
    console,
  };
  context.globalThis=context;
  vm.createContext(context);
  vm.runInContext(src,context,{filename:'gesture-client.js'});
  return {context,calls};
}

(async()=>{
  {
    const {context,calls}=make();
    const out=await context.JarvisGestureInput.sample('phone-1','open_palm');
    assert.equal(out.intent,'stop');
    assert.deepEqual(calls,[['gesture_sample','phone-1','open_palm']]);
  }
  {
    const {context,calls}=make();
    await context.JarvisGestureInput.sample('phone-1','none');
    assert.deepEqual(calls,[['gesture_sample','phone-1','none']]);
  }
  {
    const {context,calls}=make();
    await assert.rejects(()=>context.JarvisGestureInput.sample('phone-1','send_mail'),/desteklenmiyor/i);
    await assert.rejects(()=>context.JarvisGestureInput.sample('','open_palm'),/cihaz/i);
    assert.equal(calls.length,0);
  }
  {
    const {context}=make();
    context.api=null;
    await assert.rejects(()=>context.JarvisGestureInput.sample('phone-1','open_palm'),/bridge/i);
  }
  console.log('gesture client behavior: OK');
})().catch(err=>{console.error(err);process.exit(1)});
