import test from 'node:test';
import assert from 'node:assert/strict';
import { initializeReview } from '../src/signelet/assets/review.mjs';

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

test('clearing a nearby choice keeps focus connected; top controls keep their focus', () => {
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
  choose();
  const topClear = button(app, 'Clear choice');
  topClear.focus(); topClear.click();
  assert.equal(document.activeElement, topClear, 'stable top controls must not steal focus');
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
    button(currentNearby, 'Export choice').click();
    const decision = JSON.parse(await exported.text());
    assert.deepEqual(decision.choice, {note_id: 'note-0', source_offset: 0, target_offset: 1});
    assert.deepEqual(Object.fromEntries(Object.entries(decision).filter(([k]) => k !== 'choice')), original.binding);
    assert.deepEqual(payload, original, 'browser review never changes native rows, counts or binding');
    button(currentNearby, 'Clear choice').click();
    assert.equal(button(app, 'Export choice').disabled, true);
    assert.equal(button(byClass(app, 'candidate-decision')[0], 'Export choice').disabled, true);
    assert.equal(byTag(app, 'textarea')[0].value, '');
  } finally { URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke; }
});
