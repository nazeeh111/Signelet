import test from 'node:test';
import assert from 'node:assert/strict';
import { initializeReview } from '../src/signelet/assets/review.mjs';
import { mountSession } from '../src/signelet/assets/session.mjs';

// Minimal dependency-free DOM boundary. The production initializer, event
// handlers, selection/pending state and decision serializer all run unchanged.
// This does not simulate browser layout or assistive-technology announcements.
class DomNode {
  constructor(tag = '', text = '') {
    this.tagName = tag.toUpperCase(); this._text = text; this.children = [];
    this.attributes = new Map(); this.listeners = new Map(); this.parent = null;
  }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  append(...nodes) {
    for (const node of nodes) {
      node.remove(); node.parent = this; this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parent = null;
    this.children = []; this.append(...nodes);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this);
    this.parent = null;
  }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  addEventListener(type, callback) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), callback]);
  }
  dispatch(type) { for (const callback of this.listeners.get(type) || []) callback({target: this}); }
  click() { if (!this.disabled) this.dispatch('click'); }
  focus() { document.activeElement = this; }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  matches(selector) {
    if (selector !== '.candidate-decision .primary') throw new Error('unsupported DOM boundary selector');
    let parent = this.parent;
    while (parent && !parent.className?.split(' ').includes('candidate-decision')) parent = parent.parent;
    return !!parent && this.className?.split(' ').includes('primary');
  }
}
function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }
function byClass(root, name) { return descendants(root).filter(n => n.className?.split(' ').includes(name)); }
function byTag(root, tag) { return descendants(root).filter(n => n.tagName === tag.toUpperCase()); }
function button(root, text) {
  return byTag(root, 'button').find(n => n.textContent === text);
}
function fixture(count = 60) {
  return {
    binding: {schema: 'signelet-review-decision-v1', model: 'signelet-unit-codepoint-v1',
      input_file_sha256: '1'.repeat(64), source_id: 'original', target_id: 'edited',
      source_sha256: '2'.repeat(64), target_sha256: '3'.repeat(64),
      note_ids: Array.from({length: count}, (_, i) => `note-${i}`),
      limits: {max_band: 64, cell_limit: 2000000}, base_pins: []},
    source_text: 'a', target_text: 'aa', unit: 'Unicode code points',
    counts: {transposed: 0, review: count, unknown: 0, unsupported: 0},
    rows: Array.from({length: count}, (_, i) => ({id: `note-${i}`, status: 'review',
      reason: 'alignment_ambiguous_or_deleted', source: [0, 1], target: null,
      selected_text: 'a', selected_text_truncated: false,
      data_preview: `Self-authored annotation ${i}`, data_preview_truncated: false,
      endpoints: [{source_offset: 0, deletion_possible: false, candidate_count: 2,
        candidate_cap: 8, truncated: false,
        candidates: [{target_offset: 0, eligible: true}, {target_offset: 1, eligible: true}]}]})),
  };
}
function setup(payload = fixture()) {
  const app = new DomNode('main');
  globalThis.document = {createElement: tag => new DomNode(tag),
    createTextNode: text => new DomNode('', text), activeElement: null};
  initializeReview(payload, app);
  return {app, payload, search: byTag(app, 'input').find(n => n.type === 'search')};
}
function selected(app) {
  const pressed = byClass(app, 'note-button').filter(n => n.getAttribute('aria-pressed') === 'true');
  const title = byTag(byClass(app, 'note-detail')[0], 'h2');
  return {pressed: pressed.map(n => byTag(n, 'strong')[0].textContent), detail: title[0]?.textContent};
}

test('one contextual action group clears its choice without detaching keyboard focus', () => {
  const {app} = setup();
  const choose = () => {
    const radio = byTag(byClass(app, 'candidate-choices')[0], 'input')[1];
    radio.checked = true; radio.dispatch('change');
  };
  choose();
  const nearbyClear = button(byClass(app, 'candidate-decision')[0], 'Clear choice');
  nearbyClear.focus(); nearbyClear.click();
  assert.ok(descendants(app).includes(document.activeElement), 'clear must not detach focused control');
  assert.equal(document.activeElement, byClass(app, 'note-detail')[0]);
  assert.equal(byClass(app, 'candidate-decision').length, 1);
  assert.equal(byTag(app, 'button').filter(n => n.textContent === 'Clear choice').length, 1);
  assert.equal(byTag(app, 'button').filter(n => n.textContent === 'Export choice').length, 1);
  assert.equal(button(app, 'Export choice').disabled, true);
});

// Reverting visible-page selection or omitting paging's detail redraw fails this.
test('paging selects a visible note and redraws its corresponding detail', () => {
  const {app} = setup();
  assert.deepEqual(selected(app), {pressed: ['note-0'], detail: 'note-0'});
  button(app, 'Next').click();
  assert.deepEqual(selected(app), {pressed: ['note-50'], detail: 'note-50'});
  byClass(app, 'note-button')[1].click();
  assert.deepEqual(selected(app), {pressed: ['note-51'], detail: 'note-51'});
  button(app, 'Previous').click();
  assert.deepEqual(selected(app), {pressed: ['note-0'], detail: 'note-0'});
});

test('search, no matches and a missing selection keep list and detail coherent', () => {
  const {app, payload, search} = setup();
  search.value = 'note-59'; search.dispatch('input');
  assert.deepEqual(selected(app), {pressed: ['note-59'], detail: 'note-59'});
  search.value = 'missing'; search.dispatch('input');
  assert.deepEqual(selected(app), {pressed: [], detail: undefined});
  assert.match(byClass(app, 'note-detail')[0].textContent, /No notes match/);
  search.value = ''; search.dispatch('input');
  assert.deepEqual(selected(app), {pressed: ['note-0'], detail: 'note-0'});
  payload.rows.shift(); search.dispatch('input');
  assert.deepEqual(selected(app), {pressed: ['note-1'], detail: 'note-1'});
  assert.deepEqual(selected(setup(fixture(0)).app), {pressed: [], detail: undefined});
});

// Missing announcement or forced focus during selection fails this boundary.
test('note selection exposes identity and status plus an explicit route without stealing focus', () => {
  const {app} = setup();
  const note = byClass(app, 'note-button')[1]; note.focus(); note.click();
  assert.equal(document.activeElement, note);
  const status = byClass(app, 'selected-note-status')[0];
  assert.ok(status); assert.equal(status.getAttribute('role'), 'status');
  assert.equal(status.getAttribute('aria-live'), 'polite');
  assert.match(status.textContent, /note-1/); assert.match(status.textContent, /Review/);
  const route = byTag(app, 'a').find(n => n.href === '#selected-note-detail');
  assert.ok(route); assert.match(route.textContent, /selected note/i);
  assert.equal(byClass(app, 'note-detail')[0].id, 'selected-note-detail');
});

// A second pending source, clearing on paging or exporting the visible note
// rather than the chosen note fails the actual exported Blob assertions.
test('nearby pending actions retain one validated choice and export its original binding across paging', async () => {
  const {app, payload} = setup();
  const original = structuredClone(payload);
  const radios = byTag(byClass(app, 'candidate-choices')[0], 'input');
  radios[1].checked = true; radios[1].dispatch('change');
  const nearby = byClass(app, 'candidate-decision')[0];
  assert.ok(nearby); assert.match(nearby.textContent, /note-0/); assert.match(nearby.textContent, /0 → 1/);
  button(app, 'Next').click();
  assert.deepEqual(selected(app), {pressed: ['note-50'], detail: 'note-50'});
  const currentNearby = byClass(app, 'candidate-decision')[0];
  assert.match(currentNearby.textContent, /note-0/);
  let exported;
  const originalCreate = URL.createObjectURL, originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = blob => { exported = blob; return 'blob:self-authored-test'; };
  URL.revokeObjectURL = () => {};
  try {
    assert.equal(currentNearby.getAttribute('aria-label'), 'Pending choice for note note-0');
    button(currentNearby, 'Export choice for note-0').click();
    const decision = JSON.parse(await exported.text());
    assert.deepEqual(decision.choice, {note_id: 'note-0', source_offset: 0, target_offset: 1});
    assert.deepEqual(Object.fromEntries(Object.entries(decision).filter(([k]) => k !== 'choice')), original.binding);
    assert.deepEqual(payload, original, 'browser review never changes native rows, counts or binding');
    button(currentNearby, 'Clear choice').click();
    assert.equal(button(app, 'Export choice').disabled, true);
    assert.equal(byClass(app, 'candidate-decision').length, 1);
    assert.equal(byTag(app, 'textarea')[0].value, '');
  } finally { URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; }
});

test('live adapter submits a current choice and restores only an eligible pending choice',()=>{
  const {app,payload}=setup(fixture(1));let accepted=null,changed='unset';
  const pending={note_id:'note-0',source_offset:0,target_offset:1};
  initializeReview(payload,app,{pendingChoice:pending,onDecision:choice=>accepted=choice,onPending:choice=>changed=choice});
  assert.match(byClass(app,'pending-pin')[0].textContent,/0 → 1/);
  button(app,'Accept and recompute').click();assert.deepEqual(accepted,pending);
  button(app,'Clear choice').click();assert.equal(changed,null);
  initializeReview(payload,app,{pendingChoice:{...pending,target_offset:999},onDecision:()=>{}});
  assert.equal(button(app,'Accept and recompute').disabled,true);
});


test('a pending choice stays explicitly bound to its note while viewing a resolved note', () => {
  const {app,payload}=setup(fixture(2));
  payload.rows[1].status='transposed';payload.rows[1].target=[0,1];payload.rows[1].endpoints=[];
  let accepted=null;
  initializeReview(payload,app,{onDecision:choice=>accepted=choice});
  const radio=byTag(byClass(app,'candidate-choices')[0],'input')[1];radio.checked=true;radio.dispatch('change');
  const expected={note_id:'note-0',source_offset:0,target_offset:1};
  byClass(app,'note-button')[1].click();
  assert.deepEqual(selected(app),{pressed:['note-1'],detail:'note-1'});
  assert.equal(byClass(app,'candidate-choices').length,0);
  assert.equal(byClass(app,'candidate-decision').length,1);
  const group=byClass(app,'candidate-decision')[0];
  assert.equal(group.getAttribute('aria-label'),'Pending choice for note note-0');
  assert.match(group.textContent,/Pending pin: 0 → 1 · note note-0/);
  button(group,'Accept note-0 and recompute').click();assert.deepEqual(accepted,expected);
  const clear=button(group,'Clear choice');clear.focus();clear.click();
  assert.equal(document.activeElement,byClass(app,'note-detail')[0]);
  assert.equal(byClass(app,'candidate-decision').length,0);
});

test('offline and live share header before board and guides; accepted recomputation advances focus to the next review', () => {
  const {app,payload}=setup(fixture(2));
  assert.equal(app.children[0].className,'review-header');
  assert.equal(app.children[1].className,'review-layout');
  assert.ok(app.children.indexOf(byClass(app,'decision-guide')[0])>app.children.indexOf(byClass(app,'review-layout')[0]));
  assert.equal(byTag(app,'h1').length,1);
  const header=new DomNode('div');const board=new DomNode('div');
  const accepted=structuredClone(payload);accepted.rows[0].status='transposed';accepted.rows[0].target=[0,1];accepted.rows[0].endpoints=[];
  accepted.counts={transposed:1,review:1,unknown:0,unsupported:0};
  initializeReview(accepted,board,{headerTarget:header,onDecision:()=>{},focusDetail:true});
  assert.equal(header.children[0].className,'review-header');assert.equal(byTag(header,'h1').length,1);
  assert.equal(byTag(board,'h1').length,0);assert.equal(board.children[0].className,'review-layout');
  assert.deepEqual(selected(board),{pressed:['note-1'],detail:'note-1'});
  assert.equal(document.activeElement,byClass(board,'note-detail')[0]);
  assert.equal(byClass(board,'full-resources').length,1);assert.equal(byClass(board,'binding-details').length,1);
  assert.equal(byClass(board,'candidate-decision').length,1);
});

test('mounted session keeps toolbar focus and busy/cancel/reload ownership while late responses cannot commit another note', async () => {
  const {payload}=setup(fixture(2));const root=new DomNode('main');
  const initial={revision:'initial',assumptions:0,status:'review_required',payload};
  const changed=structuredClone(initial);changed.revision='saved';changed.assumptions=1;
  changed.payload.rows[0].status='transposed';changed.payload.rows[0].target=[0,1];changed.payload.rows[0].endpoints=[];
  changed.payload.counts={transposed:1,review:1,unknown:0,unsupported:0};
  let resolveStep;let state=initial;const sent=[];
  const controller=mountSession(root,'owned-synthetic-test',async(path,options)=>{
    sent.push([path,options?.body&&JSON.parse(options.body)]);
    if(path==='/api/step')return new Promise(resolve=>{resolveStep=view=>resolve({ok:true,json:async()=>view});});
    return {ok:true,json:async()=>state};
  });
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};await settle();
  const content=root.children.find(n=>n.id==='review-content');const reload=button(root,'Reload saved state');
  assert.equal(button(root,'Stop waiting').hidden,true);
  const radio=byTag(byClass(content,'candidate-choices')[0],'input')[1];radio.checked=true;radio.dispatch('change');
  const accept=button(content,'Accept and recompute');accept.focus();accept.click();await settle();
  assert.equal(content.inert,true);assert.equal(content.getAttribute('aria-busy'),'true');
  assert.equal(button(root,'Save session file').disabled,true);assert.equal(reload.disabled,true);
  const cancel=button(root,'Stop waiting');assert.equal(cancel.hidden,false);cancel.focus();cancel.click();
  assert.equal(controller.needsReload,true);assert.equal(content.inert,true);assert.equal(cancel.hidden,true);
  state=changed;resolveStep(changed);await settle();assert.equal(controller.current.revision,'initial');
  reload.focus();reload.click();await settle();assert.equal(controller.current.revision,'saved');
  assert.equal(document.activeElement,reload);assert.ok(root.contains(reload));assert.equal(content.inert,false);
  assert.deepEqual(selected(content),{pressed:['note-1'],detail:'note-1'});
  const steps=sent.filter(([path])=>path==='/api/step');assert.equal(steps.length,1);
  assert.deepEqual(steps[0][1].choice,{note_id:'note-0',source_offset:0,target_offset:1});
  assert.equal(byClass(content,'candidate-decision').length,1);assert.match(byClass(content,'candidate-decision')[0].textContent,/No new pin selected/);
  const final=structuredClone(changed);final.revision='complete';final.assumptions=2;final.status='complete';
  final.payload.rows[1].status='transposed';final.payload.rows[1].target=[0,1];final.payload.rows[1].endpoints=[];
  const nextRadio=byTag(byClass(content,'candidate-choices')[0],'input')[1];nextRadio.checked=true;nextRadio.dispatch('change');
  const nextAccept=button(content,'Accept and recompute');nextAccept.focus();nextAccept.click();await settle();resolveStep(final);await settle();
  assert.equal(controller.current.revision,'complete');assert.equal(document.activeElement,byClass(content,'note-detail')[0]);
});
