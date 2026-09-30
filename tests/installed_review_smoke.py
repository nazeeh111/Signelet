"""Verify the installed offline page -> bound decision -> native result boundary."""

import hashlib
from importlib import metadata, resources
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import signelet
from stam import AnnotationStore


def payload(page):
    match = re.search(r'<script id="signelet-data" type="application/json">(.*?)</script>', page, re.S)
    assert match, 'missing inert review data'
    return json.loads(match.group(1))


def verify(example, root):
    root.mkdir(exist_ok=False)
    console = Path(sys.executable).parent / 'signelet'
    assert 'site-packages' in signelet.__file__
    assert metadata.version('signelet') == signelet.__version__
    assert metadata.version('stam') == '0.12.1'
    source = root / 'input.stam.json'
    original = example.read_bytes()
    source.write_bytes(original)
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    outcomes = []

    def run(name, expected, file=source, extra=()):
        result = subprocess.run([str(console), str(file), *map(str, extra), '--output', str(root/name)], cwd=root, env=environment, capture_output=True, text=True)
        assert result.returncode == expected, (name, result.stdout, result.stderr)
        outcomes.append({'run': name, 'exit': result.returncode})
        if expected == 2:
            assert not (root/name).exists()
            return None
        page = (root/name/'review.html').read_text()
        assets = resources.files('signelet').joinpath('assets')
        assert assets.joinpath('review.mjs').read_text() in page
        assert assets.joinpath('review.css').read_text() in page
        assert "connect-src 'none'" in page and 'Content-Security-Policy' in page
        return payload(page)

    context = ['--source', 'original', '--target', 'edited', '--note', 'very', '--note', 'boat']
    review = run('review', 1, extra=context)
    decision = root/'choice.json'
    decision.write_text(json.dumps(review['binding'] | {'choice': {'note_id': 'very', 'source_offset': 4, 'target_offset': 9}}))
    resolved = run('resolved', 0, extra=['--decision', decision])
    assert resolved['binding']['base_pins'] == [[4,9]]
    store = AnnotationStore(file=str(root/'resolved/store.stam.json'))
    ledger = json.loads((root/'resolved/review-ledger.json').read_text())
    for row, wanted in zip(ledger['rows'], [[9,13],[19,23]]):
        selection = list(store.annotation(row['output_note_id']).textselections())[0]
        assert [selection.begin(), selection.end()] == wanted
    run('override', 2, extra=['--decision', decision, '--cell-limit', '0'])
    source.write_bytes(original+b'\n')
    run('stale', 2, extra=['--decision', decision])
    source.write_bytes(original)
    malformed = root/'malformed.json'; malformed.write_text(decision.read_text().replace('"source_offset": 4', '"source_offset": true'))
    run('malformed', 2, extra=['--decision', malformed])
    unknown = run('unknown', 1, extra=context+['--pin','4:9','--cell-limit','0'])
    assert unknown['binding']['base_pins'] == [[4,9]]
    assert all(not row['endpoints'] for row in unknown['rows'])

    # Two independently repeated regions need two native recomputation rounds.
    document = json.loads(original)
    document['resources'][0]['text'] = 'The very blue blue boat.'
    document['resources'][1]['text'] = 'The very very blue blue blue boat.'
    document['annotations'][1]['@id'] = 'blue'
    document['annotations'][1]['target']['offset']['begin']['value'] = 9
    document['annotations'][1]['target']['offset']['end']['value'] = 13
    rounds = root/'rounds.stam.json'; rounds.write_text(json.dumps(document))
    first = run('round-start', 1, file=rounds, extra=['--source','original','--target','edited','--note','very','--note','blue'])
    choice1 = root/'choice1.json'; choice1.write_text(json.dumps(first['binding'] | {'choice': {'note_id':'very','source_offset':4,'target_offset':9}}))
    second = run('round-second', 1, file=rounds, extra=['--decision',choice1])
    assert second['binding']['base_pins'] == [[4,9]]
    choice2 = root/'choice2.json'; choice2.write_text(json.dumps(second['binding'] | {'choice': {'note_id':'blue','source_offset':9,'target_offset':19}}))
    final = run('round-final', 0, file=rounds, extra=['--decision',choice2])
    assert final['binding']['base_pins'] == [[4,9],[9,19]]
    native = AnnotationStore(file=str(root/'round-final/store.stam.json'))
    ledger = json.loads((root/'round-final/review-ledger.json').read_text())
    assert {row['id']:row['target'] for row in ledger['rows']} == {'very':[9,13],'blue':[19,23]}
    for row in ledger['rows']:
        assert list(native.annotation(row['output_note_id']).textselections())[0].text() == row['exact']
    assert source.read_bytes() == original
    evidence = {'python':sys.version,'stam':metadata.version('stam'),'installed_module':signelet.__file__,
                'package_assets_exactly_embedded':True,'outside_checkout':True,
                'original_sha256':hashlib.sha256(original).hexdigest(),'input_unchanged':True,'outcomes':outcomes,
                'final_cumulative_pins':final['binding']['base_pins']}
    (root/'installed-review-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__ == '__main__':
    assert len(sys.argv)==3, 'Provide public fixture and a new evidence directory'
    verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
