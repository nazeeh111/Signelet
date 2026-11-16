import test from 'node:test';
import assert from 'node:assert/strict';
import {SessionController} from '../src/signelet/assets/session.mjs';

function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
test('late cancelled results never replace last valid state and require reconciliation',async()=>{
  let request=deferred();const views=[],messages=[],calls=[];
  const controller=new SessionController((op,body)=>{calls.push([op,body]);return request.promise;},v=>views.push(v),(text,busy)=>messages.push([text,busy]));
  let running=controller.request('state');request.resolve({revision:'first'});await running;
  request=deferred();running=controller.request('step',{choice:{note_id:'invented',source_offset:1,target_offset:2}});
  assert.equal(await controller.request('undo'),false);controller.cancel();
  request.resolve({revision:'late'});assert.equal(await running,false);assert.equal(controller.current.revision,'first');assert.equal(views.length,1);
  assert.equal(await controller.request('step'),false);
  request=deferred();running=controller.request('state');request.resolve({revision:'reconciled'});await running;
  assert.equal(controller.current.revision,'reconciled');assert.equal(controller.needsReload,false);
});
test('failed work retains view and session text is transported opaquely',async()=>{
  const views=[];let fail=false;const bodies=[];
  const c=new SessionController(async(op,body)=>{bodies.push(body);if(fail)throw new Error('storage unavailable');return {revision:'kept'};},v=>views.push(v),()=>{});
  await c.request('state');fail=true;assert.equal(await c.request('undo'),false);assert.equal(c.current.revision,'kept');assert.equal(views.length,1);
  fail=false;await c.request('state');
  const text='{"exact":9007199254740993,"float":0.0,"flag":true}';await c.request('import',{journal_text:text});
  assert.equal(bodies.at(-1).journal_text,text);
});
test('late file reads cannot overwrite a newer open or another accepted operation',async()=>{
  const sent=[];const c=new SessionController(async(op,body)=>{sent.push([op,body]);return {revision:String(sent.length)};},()=>{},()=>{});
  await c.request('state');const a=deferred(),b=deferred();
  const first=c.open(()=>a.promise),second=c.open(()=>b.promise);
  b.resolve('newer opaque text');await second;a.resolve('older opaque text');assert.equal(await first,false);
  assert.equal(sent.filter(([op])=>op==='import').length,1);assert.equal(sent.at(-1)[1].journal_text,'newer opaque text');
  const late=deferred(),opening=c.open(()=>late.promise);await c.request('undo');late.resolve('stale after another operation');assert.equal(await opening,false);
});
