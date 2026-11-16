import {initializeReview} from './review.mjs';

// One request generation owns display updates; the server owns accepted decisions.
export class SessionController {
  constructor(transport, render, notify) {
    this.transport=transport;this.render=render;this.notify=notify;
    this.generation=0;this.current=null;this.abort=null;this.busy=false;this.needsReload=false;this.openGeneration=0;
  }
  async request(operation,extra={}) {
    if(this.busy||this.needsReload&&operation!=='state'){this.notify(this.busy?'Wait for the current request or stop waiting.':'Reload saved state before another choice.',this.busy);return false;}
    const generation=++this.generation;this.abort=new AbortController();this.busy=true;
    this.notify('Recomputing and saving…',true);
    try {
      const result=await this.transport(operation,{revision:this.current?.revision,...extra},this.abort.signal);
      if(generation!==this.generation)return false;
      this.needsReload=false;this.current=result;this.render(result);this.notify('Saved. Agreement remains conditional on the recorded assumptions.',false);return true;
    } catch(error) {
      if(generation===this.generation){this.needsReload=true;this.notify(`${error.message} Last valid review retained. Reload saved state before retry.`,false);}
      return false;
    } finally {
      if(generation===this.generation){this.busy=false;this.abort=null;}
    }
  }
  async open(readText) {
    const generation=this.generation,opening=++this.openGeneration;
    try {
      const text=await readText();
      if(generation!==this.generation||opening!==this.openGeneration)return false;
      return await this.request('import',{journal_text:text});
    } catch(error) {
      if(generation===this.generation&&opening===this.openGeneration)this.notify(error.message+' Last saved review retained.',false);
      return false;
    }
  }
  cancel() {
    ++this.generation;this.needsReload=true;this.abort?.abort();this.abort=null;this.busy=false;
    this.notify('Stopped waiting. A choice may already be saved. Reload saved state to reconcile before another choice.',false);
  }
}

export function mountSession(root,nonce,fetcher=fetch) {
  function node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  const toolbar=node('section');toolbar.className='decision-bar session-toolbar';toolbar.setAttribute('aria-label','Saved review session');
  toolbar.append(node('h2','Continue your review'));
  const help=node('p','Each accepted character choice is recomputed and saved here. Your original notes stay unchanged. A completed transfer is conditional on your assumptions.');
  const message=node('p','Loading saved state…');message.setAttribute('role','status');message.setAttribute('aria-live','polite');
  const reload=node('button','Reload saved state'),cancel=node('button','Stop waiting'),undo=node('button','Undo last accepted choice');
  const save=node('button','Save session file'),bundle=node('button','Download current native bundle');
  const openLabel=node('label','Open saved session for these same notes '),open=node('input');open.type='file';open.accept='.json,application/json';openLabel.append(open);
  const progress=node('p');progress.className='counts';
  const content=node('div');content.id='review-content';
  const actions=node('div');actions.className='session-actions';actions.append(reload,cancel,undo,save,bundle);
  toolbar.append(node('p','Saved session files and bundles contain original and edited texts and note data. Keep them with your project.'),help,progress,actions,openLabel,message);root.replaceChildren(toolbar,content);
  async function transport(operation,body,signal){
    const response=await fetcher(operation==='state'?'/api/state':`/api/${operation}`,operation==='state'?{signal}:{method:'POST',headers:{'Content-Type':'application/json','X-Signelet-Session':nonce},body:JSON.stringify(body),signal});
    const result=await response.json();if(!response.ok)throw new Error(result.error||`Request failed (${response.status})`);return result;
  }
  let pending=null,pendingRevision=null;
  const controller=new SessionController(transport,view=>{
    if(view.revision!==pendingRevision)pending=null;
    progress.textContent=`${view.assumptions} accepted ${view.assumptions===1?'assumption':'assumptions'} · ${view.status==='complete'?'All selected notes transferred':'Review still required'}`;
    initializeReview(view.payload,content,{onDecision:choice=>controller.request('step',{choice}),pendingChoice:pending,onPending:choice=>{pending=choice;pendingRevision=view.revision;}});
    undo.disabled=!view.assumptions;
  },(text,busy)=>{
    message.textContent=text;content.inert=busy||controller.needsReload;content.setAttribute('aria-busy',String(busy));
    for(const button of [reload,undo,save,bundle])button.disabled=busy;
    open.disabled=busy;cancel.disabled=!busy;
    if(!busy&&controller.current)undo.disabled=!controller.current.assumptions;
  });
  reload.addEventListener('click',()=>controller.request('state'));
  cancel.addEventListener('click',()=>controller.cancel());
  undo.addEventListener('click',()=>controller.request('undo'));
  async function download(path,name){
    const generation=controller.generation;
    try {
      const response=await fetcher(path);if(!response.ok)throw new Error('Download refused');
      const blob=await response.blob();const url=URL.createObjectURL(blob),anchor=node('a');anchor.href=url;anchor.download=name;root.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
      if(generation===controller.generation)message.textContent='Download requested. Keep the session file to reopen and replay the assumptions.';
    } catch(error){if(generation===controller.generation)message.textContent=error.message+' Last saved review retained.';}
  }
  save.addEventListener('click',()=>download('/api/journal','signelet-session.json'));
  bundle.addEventListener('click',()=>download('/api/bundle','signelet-native-review.zip'));
  open.addEventListener('change',async()=>{
    const file=open.files?.[0];if(!file)return;
    if(file.size>8*1024*1024){message.textContent='Session file exceeds8MiB. Last saved review retained.';return;}
    try {await controller.open(()=>file.text());}
    finally{if(open.files?.[0]===file)open.value='';}
  });
  controller.request('state');return controller;
}
if(typeof document!=='undefined'){
  const root=document.getElementById('session'),data=document.getElementById('session-bootstrap');
  if(root&&data)mountSession(root,JSON.parse(data.textContent).nonce);
}
