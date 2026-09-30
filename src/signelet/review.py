"""Offline review context and input-bound assumptions for native recomputation."""

import base64
import hashlib
from importlib import resources
import json
import math
import os
from pathlib import Path
import stat

from ._alignment import align, MAX_CHARS, MAX_BYTES
from .adapter import MAX_STORE_BYTES, MAX_NOTES, data_values, _diagnostics

SCHEMA = 'signelet-review-decision-v1'
MODEL = 'signelet-unit-codepoint-v1'
BINDING_KEYS = {'schema', 'model', 'input_file_sha256', 'source_id', 'target_id',
                'source_sha256', 'target_sha256', 'note_ids', 'limits', 'base_pins'}


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def parse_decision(raw):
    """Read bounded finite JSON without duplicate keys or excessive nesting."""
    if len(raw) > MAX_STORE_BYTES:
        raise ValueError('decision exceeds 4 MiB')

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate decision JSON key')
            value[key] = item
        return value

    def constant(value):
        raise ValueError('nonfinite decision JSON constant')

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (RecursionError, UnicodeError) as error:
        raise ValueError('invalid decision JSON') from error
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError('decision nesting exceeds 32')
        if type(item) is float and not math.isfinite(item):
            raise ValueError('nonfinite decision JSON number')
        children = item.values() if type(item) is dict else item if type(item) is list else ()
        pending.extend((child, depth + 1) for child in children)
    return value


def read_decision(path):
    """Open only a bounded regular decision file, never a FIFO or external include."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('decision must be a regular nonsymlink file')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        initial = os.fstat(handle.fileno())
        if (not stat.S_ISREG(initial.st_mode) or initial.st_size > MAX_STORE_BYTES
                or (initial.st_ino, initial.st_dev) != (before.st_ino, before.st_dev)):
            raise ValueError('invalid or oversized decision file')
        raw = handle.read(MAX_STORE_BYTES + 1)
        after = os.fstat(handle.fileno())
        if (len(raw) != initial.st_size or (after.st_size, after.st_mtime_ns)
                != (initial.st_size, initial.st_mtime_ns)):
            raise ValueError('decision changed while reading')
    return parse_decision(raw)


def _texts(store, source_id, target_id):
    if (type(source_id) is not str or not source_id or type(target_id) is not str
            or not target_id or source_id == target_id):
        raise ValueError('distinct source and target resource IDs required')
    old, new = store.resource(source_id).text(), store.resource(target_id).text()
    if max(len(old), len(new)) > MAX_CHARS:
        raise ValueError('resource code-point budget exceeded')
    if max(len(old.encode('utf-8')), len(new.encode('utf-8'))) > MAX_BYTES:
        raise ValueError('resource byte budget exceeded')
    return old, new


def _pins(pins, old, new):
    if type(pins) not in (list, tuple) or len(pins) > 2000:
        raise ValueError('invalid baseline pins')
    previous = (-1, -1)
    fixed = []
    for pair in pins:
        if (type(pair) not in (list, tuple) or len(pair) != 2
                or any(type(offset) is not int for offset in pair)):
            raise ValueError('pins require two integer code-point offsets')
        i, j = pair
        if not previous[0] < i < len(old) or not previous[1] < j < len(new) or old[i] != new[j]:
            raise ValueError('pins crossed, duplicated, unequal or out of range')
        previous = (i, j)
        fixed.append([i, j])
    return fixed


def _compatible(pins, i, j):
    return all((i < left and j < right) or (i > left and j > right) for left, right in pins)


def _binding(raw, source_id, target_id, old, new, note_ids, pins, max_band, cell_limit):
    return {'schema': SCHEMA, 'model': MODEL, 'input_file_sha256': _hash(raw),
            'source_id': source_id, 'target_id': target_id,
            'source_sha256': _hash(old.encode('utf-8')), 'target_sha256': _hash(new.encode('utf-8')),
            'note_ids': list(note_ids), 'limits': {'max_band': max_band, 'cell_limit': cell_limit},
            'base_pins': _pins(pins, old, new)}


def build_payload(raw, store, report, source_id, target_id, note_ids, pins, max_band, cell_limit):
    """Embed raw resources once; contexts are derived from code-point offsets."""
    old, new = _texts(store, source_id, target_id)
    binding = _binding(raw, source_id, target_id, old, new, note_ids, pins, max_band, cell_limit)
    rows = []
    for original in report['rows']:
        span = original.get('source')
        selected = old[span[0]:span[1]] if span else ''
        # This is a bounded display preview, not a new interchange representation.
        preview = json.dumps(data_values(store.annotation(original['id'])),
                             ensure_ascii=False, default=str)
        row = {'id': original['id'], 'status': original['status'], 'reason': original.get('reason'),
               'source': span, 'target': original.get('target'), 'selected_text': selected[:128],
               'selected_text_truncated': len(selected) > 128, 'data_preview': preview[:512],
               'data_preview_truncated': len(preview) > 512, 'endpoints': []}
        for endpoint in original.get('pin_diagnostics', {}).get('endpoints', []):
            i = endpoint['source_offset']
            candidates = [{'target_offset': candidate['target_offset'],
                           'eligible': candidate['equal_character']
                           and len(binding['base_pins']) < 2000
                           and (endpoint['candidate_count'] > 1 or endpoint['deletion_possible'])
                           and _compatible(binding['base_pins'], i, candidate['target_offset'])}
                          for candidate in endpoint['candidates']]
            row['endpoints'].append({key: endpoint[key] for key in
                ['source_offset', 'deletion_possible', 'candidate_count', 'candidate_cap', 'truncated']}
                | {'candidates': candidates})
        rows.append(row)
    return {'binding': binding, 'source_text': old, 'target_text': new,
            'unit': 'Unicode code points', 'counts': report['counts'], 'rows': rows}


def validate_decision(raw, store, decision):
    """Validate one offered assumption under prior pins, then return integration args.

    Decision files are unsigned. They express user assumptions, not authenticated
    approvals. Recomputing the current candidate set prevents stale hints being
    mistaken for a certificate under a different model.
    """
    if type(decision) is not dict or set(decision) != BINDING_KEYS | {'choice'}:
        raise ValueError('invalid decision fields')
    if decision['schema'] != SCHEMA or type(decision['schema']) is not str or decision['model'] != MODEL:
        raise ValueError('unsupported decision schema or model')
    limits = decision['limits']
    if (type(limits) is not dict or set(limits) != {'max_band', 'cell_limit'}
            or type(limits['max_band']) is not int or not 0 <= limits['max_band'] <= 64
            or type(limits['cell_limit']) is not int or not 0 <= limits['cell_limit'] <= 2000000):
        raise ValueError('invalid decision limits')
    names = decision['note_ids']
    if (type(names) is not list or not 1 <= len(names) <= MAX_NOTES
            or any(type(name) is not str or not name for name in names) or len(set(names)) != len(names)):
        raise ValueError('unique bounded decision note IDs required')
    for name in names:
        store.annotation(name)
    old, new = _texts(store, decision['source_id'], decision['target_id'])
    pins = _pins(decision['base_pins'], old, new)
    expected = _binding(raw, decision['source_id'], decision['target_id'], old, new,
                        names, pins, limits['max_band'], limits['cell_limit'])
    if {key: decision[key] for key in BINDING_KEYS} != expected:
        raise ValueError('decision does not match exact input bytes and resource hashes')
    choice = decision['choice']
    if (type(choice) is not dict or set(choice) != {'note_id', 'source_offset', 'target_offset'}
            or type(choice['note_id']) is not str or choice['note_id'] not in names
            or type(choice['source_offset']) is not int or type(choice['target_offset']) is not int):
        raise ValueError('invalid single decision choice')
    note = store.annotation(choice['note_id'])
    selector = json.loads(note.json())['target']
    if selector.get('@type') != 'TextSelector' or selector.get('resource') != decision['source_id']:
        raise ValueError('chosen note requires a direct source TextSelector')
    selections = list(note.textselections())
    if len(selections) != 1:
        raise ValueError('chosen note requires one contiguous selection')
    s, e = selections[0].begin(), selections[0].end()
    i, j = choice['source_offset'], choice['target_offset']
    if not 0 <= s < e <= len(old) or i not in (s, e - 1) or not 0 <= j < len(new):
        raise ValueError('choice is not a note endpoint within the resources')
    if old[i] != new[j] or not _compatible(pins, i, j) or len(pins) == 2000:
        raise ValueError('choice is unequal or conflicts with baseline pins')
    result = align(old, new, pins, **limits)
    if result['status'] != 'complete':
        raise ValueError('decision candidate cannot be verified within alignment budget')
    options = result['choices'][s:e]
    if all(len(values) == 1 and None not in values for values in options):
        mapped = [next(iter(values)) for values in options]
        if mapped == list(range(mapped[0], mapped[-1] + 1)) and old[s:e] == new[mapped[0]:mapped[-1]+1]:
            raise ValueError('chosen note is already certified; no review candidate offered')
    diagnostics = _diagnostics(old, new, s, e, result['choices'])
    endpoint = next(item for item in diagnostics['endpoints'] if item['source_offset'] == i)
    if endpoint['candidate_count'] <= 1 and not endpoint['deletion_possible']:
        raise ValueError('endpoint position is already agreed; no new assumption offered')
    if not any(candidate['target_offset'] == j and candidate['equal_character'] for candidate in endpoint['candidates']):
        raise ValueError('choice was not offered among the bounded current candidates')
    return {'source_id': decision['source_id'], 'target_id': decision['target_id'],
            'note_ids': names, 'pins': sorted(pins + [[i, j]]), **limits}


def render_html(payload):
    """Package-contained, text-only UI with no external assets or network policy."""
    assets = resources.files('signelet').joinpath('assets')
    javascript = assets.joinpath('review.mjs').read_text(encoding='utf-8')
    css = assets.joinpath('review.css').read_text(encoding='utf-8')
    def csp_hash(text):
        return base64.b64encode(hashlib.sha256(text.encode('utf-8')).digest()).decode('ascii')
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    for literal, escaped in [('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        data = data.replace(literal, escaped)
    policy = ("default-src 'none'; connect-src 'none'; frame-src 'none'; object-src 'none'; "
              "base-uri 'none'; form-action 'none'; "
              f"script-src 'sha256-{csp_hash(javascript)}'; style-src 'sha256-{csp_hash(css)}'")
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
            '<title>Signelet annotation review</title><style>' + css + '</style></head><body>'
            '<main id="app"></main><noscript>This local review page needs JavaScript for display and decision export. '
            'Use review-ledger.json and the CLI if scripting is disabled.</noscript>'
            '<script id="signelet-data" type="application/json">' + data + '</script>'
            '<script type="module">' + javascript + '</script></body></html>\n')
