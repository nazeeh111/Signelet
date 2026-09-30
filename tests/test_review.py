"""Decision and review boundaries over actual native STAM stores."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from signelet.adapter import integrate
from signelet.review import build_payload, validate_decision, parse_decision, read_decision, render_html
from test_native import fixture


class ReviewBoundary(unittest.TestCase):
    def setUp(self):
        self.store = fixture('The very blue boat.', 'The very very blue boat.', [('very', 4, 8), ('boat', 14, 18)])
        self.raw = self.store.to_json_string().encode()
        _, self.report = integrate(self.store, 'old', 'new', ['very', 'boat'])
        self.payload = build_payload(self.raw, self.store, self.report, 'old', 'new', ['very', 'boat'], [], 64, 2000000)
        self.decision = self.payload['binding'] | {'choice': {'note_id': 'very', 'source_offset': 4, 'target_offset': 9}}

    def test_bound_choice_recomputes_native_result(self):
        context = validate_decision(self.raw, self.store, self.decision)
        output, report = integrate(self.store, **context)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['rows'][0]['target'], [9, 13])
        self.assertEqual(self.payload['rows'][0]['status'], 'review')
        self.assertEqual(self.payload['binding']['input_file_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.payload['rows'][0]['endpoints'][0]['candidates'], [{'target_offset': 4, 'eligible': True}, {'target_offset': 9, 'eligible': True}])

    def test_cumulative_pins_and_unknown_context(self):
        store = fixture('The very blue blue boat.', 'The very very blue blue blue boat.', [('very', 4, 8), ('blue', 9, 13)])
        raw = store.to_json_string().encode()
        _, report = integrate(store, 'old', 'new', ['very', 'blue'], pins=[(4, 9)])
        payload = build_payload(raw, store, report, 'old', 'new', ['very', 'blue'], [(4, 9)], 64, 2000000)
        decision = payload['binding'] | {'choice': {'note_id': 'blue', 'source_offset': 9, 'target_offset': 19}}
        context = validate_decision(raw, store, decision)
        self.assertEqual(context['pins'], [[4, 9], [9, 19]])
        _, resolved = integrate(store, **context)
        self.assertEqual(resolved['status'], 'complete')
        _, unknown = integrate(store, 'old', 'new', ['very', 'blue'], pins=[(4, 9)], cell_limit=0)
        self.assertNotIn('pins', unknown['alignment'])
        page = build_payload(raw, store, unknown, 'old', 'new', ['very', 'blue'], [(4, 9)], 64, 0)
        self.assertEqual(page['binding']['base_pins'], [[4, 9]])
        self.assertTrue(all(not row['endpoints'] for row in page['rows']))

    def test_unicode_resources_are_once_and_offsets_raw(self):
        old = '🙂The very blue boat.\r\ne\u0301'
        store = fixture(old, '🙂The very very blue boat.\r\ne\u0301', [('very', 5, 9)])
        raw = store.to_json_string().encode()
        _, report = integrate(store, 'old', 'new', ['very'])
        page = build_payload(raw, store, report, 'old', 'new', ['very'], [], 64, 2000000)
        self.assertEqual(page['source_text'], old)
        self.assertEqual(page['rows'][0]['source'], [5, 9])
        self.assertEqual(page['rows'][0]['selected_text'], 'very')
        self.assertEqual(page['rows'][0]['endpoints'][0]['candidates'][1]['target_offset'], 10)
        self.assertNotIn('context', json.dumps(page['rows']))

    def test_stale_typed_and_unoffered_choices_refused(self):
        for key, value in [('schema', ['signelet-review-decision-v1']), ('model', 'different'), ('input_file_sha256', '0'*64), ('source_sha256', '0'*64), ('note_ids', ['very', 'very']), ('base_pins', [[True, 9]]), ('limits', {'max_band': True, 'cell_limit': 2000000})]:
            decision = copy.deepcopy(self.decision); decision[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_decision(self.raw, self.store, decision)
        for choice in [None, [], {'note_id': 'very', 'source_offset': True, 'target_offset': 9}, {'note_id': 'very', 'source_offset': 5, 'target_offset': 10}, {'note_id': 'boat', 'source_offset': 14, 'target_offset': 19}, {'note_id': 'very', 'source_offset': 4, 'target_offset': 14}, {'note_id': 'very', 'source_offset': 4, 'target_offset': 999}]:
            decision = copy.deepcopy(self.decision); decision['choice'] = choice
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                validate_decision(self.raw, self.store, decision)
        with self.assertRaises(ValueError):
            validate_decision(self.raw+b'\n', self.store, self.decision)

    def test_already_agreed_endpoints_do_not_offer_a_pin_loop(self):
        store = fixture('ab', 'aXb', [('note', 0, 2)])
        raw = store.to_json_string().encode()
        _, report = integrate(store, 'old', 'new', ['note'])
        page = build_payload(raw, store, report, 'old', 'new', ['note'], [], 64, 2000000)
        self.assertEqual(page['rows'][0]['status'], 'review')
        for endpoint, target in [(0, 0), (1, 2)]:
            options = page['rows'][0]['endpoints'][endpoint]['candidates']
            self.assertEqual(options, [{'target_offset': target, 'eligible': False}])
            decision = page['binding'] | {'choice': {'note_id': 'note', 'source_offset': endpoint, 'target_offset': target}}
            with self.assertRaisesRegex(ValueError, 'already agreed'):
                validate_decision(raw, store, decision)

    def test_pin_limit_never_offers_an_unimportable_choice(self):
        store = fixture('a' * 2002, 'a' * 2003, [('note', 2000, 2001)])
        raw = store.to_json_string().encode()
        pins = [[i, i] for i in range(2000)]
        _, report = integrate(store, 'old', 'new', ['note'], pins=pins)
        page = build_payload(raw, store, report, 'old', 'new', ['note'], pins, 64, 2000000)
        self.assertEqual(len(page['binding']['base_pins']), 2000)
        self.assertTrue(all(not candidate['eligible'] for candidate in page['rows'][0]['endpoints'][0]['candidates']))
        decision = page['binding'] | {'choice': {'note_id': 'note', 'source_offset': 2000, 'target_offset': 2001}}
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            validate_decision(raw, store, decision)

    def test_literal_html_embedding_and_packaged_assets(self):
        import base64
        from importlib import resources
        import re
        hostile = '</script><img src="https://example.invalid/x">&\u2028'
        store = fixture(hostile, hostile, [('hostile', 0, len(hostile))])
        raw = store.to_json_string().encode()
        _, report = integrate(store, 'old', 'new', ['hostile'])
        page = build_payload(raw, store, report, 'old', 'new', ['hostile'], [], 64, 2000000)
        html = render_html(page)
        embedded = re.search(r'<script id="signelet-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        self.assertNotIn('<', embedded)
        self.assertNotIn('&', embedded)
        self.assertEqual(json.loads(embedded), page)
        for asset in ['review.mjs', 'review.css']:
            text = resources.files('signelet').joinpath('assets', asset).read_text(encoding='utf-8')
            digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
            self.assertIn("'sha256-" + digest + "'", html)
            self.assertIn(text, html)
        self.assertIn("connect-src 'none'", html)

    def test_regular_bounded_decision_file(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'choice.json'
            file.write_text(json.dumps(self.decision))
            self.assertEqual(read_decision(file), self.decision)
            link = Path(directory) / 'link.json'
            link.symlink_to(file)
            with self.assertRaises(ValueError):
                read_decision(link)
            with self.assertRaises(ValueError):
                read_decision(Path(directory))
            file.write_bytes(b' ' * (4 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError):
                read_decision(file)
            if hasattr(os, 'mkfifo'):
                fifo = Path(directory) / 'fifo.json'
                os.mkfifo(fifo)
                with self.assertRaises(ValueError):
                    read_decision(fifo)

    def test_strict_decision_json(self):
        for raw in [b'{"schema":1,"schema":2}', b'{"choice":NaN}', b'{"choice":Infinity}', b'{"choice":1e999}', b'['*40+b'0'+b']'*40, b' '* (4*1024*1024+1)]:
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                parse_decision(raw)


if __name__ == '__main__':
    unittest.main()
