# Signelet

Transfer text notes between edited documents only when every best alignment agrees on their destination. Signelet is an optional policy for native [STAM](https://annotation.github.io/stam) annotation stores. STAM handles resources, note data, transposition and provenance; Signelet decides which selected notes can safely use that machinery under a fixed edit model.

![Signelet repeated-word example: inserting another “very” leaves two possible target positions, 4 and 9, for the first source character; choosing pin 4:9 transfers the note to offsets 9 to 13.](docs/assets/repeated-word.svg)

Ambiguous, deleted or changed notes stay in the output with a review status. Budget exhaustion is `unknown`. No omitted span is counted as resolved.

## Install

Python 3.12 or newer is required. Install the source directory or a built wheel:

```sh
python -m pip install .
# or: python -m pip install signelet-0.2.0-py3-none-any.whl
signelet --version
```

Installation also downloads the required `stam==0.12.1` dependency unless it is already available. Runtime is local and makes no network requests. Signelet's original code is MIT; STAM is GPL-3.0-only and is neither bundled nor relicensed. See [dependency and lineage notes](THIRD-PARTY-NOTICES.md).

## Try the example

The example is in the source archive, not installed into your working directory by a wheel. If you installed only the wheel, unpack the matching source archive and enter it first:

```sh
tar -xzf signelet-0.2.0.tar.gz
cd signelet-0.2.0
```

The shipped native STAM store contains original text `The very blue boat.`, edited text `The very very blue boat.`, and two self-authored notes. Run it into a new directory:

```sh
signelet examples/repeated.stam.json --source original --target edited \
  --note very --note boat --output result-review
```

Exit code 1 is expected: `boat` transfers to `[19,23)`; `very` stays unresolved. Open `result-review/review.html` locally. It shows original context, candidate occurrences and native note statuses. Choose the first-character candidate **4 → 9**, then download `signelet-choice.json`. If the browser does not save the download, copy the page's Decision JSON into that file.

Recompute from the same original input into a new directory:

```sh
signelet examples/repeated.stam.json --decision signelet-choice.json --output result-pinned
```

This returns 0 and transfers `very` to `[9,13)`. Decision mode supplies the resource IDs, selected notes, limits and prior pins; combining it with direct context flags is refused. Each page permits one new character assumption. Its statuses stay unchanged until native recomputation; first/last hints do not certify a combined span. The next page retains all earlier pins, including when alignment is unknown.

For a manual pin or a browser without scripting, `review-ledger.json` retains the same diagnostic workflow:

```sh
signelet examples/repeated.stam.json --source original --target edited \
  --note very --note boat --pin 4:9 --output result-manual
```

Pins are user assumptions; certainty is conditional on those pins and the edit model.

A completed run (exit 0 or 1) produces `store.stam.json`, `review-ledger.json` and `review.html`. Originals remain in the store. Ledger rows identify transferred notes and native provenance outputs or explain refusal. Exit codes: **0** all requested notes transferred; **1** valid result with review, unknown or unsupported notes; **2** input/runtime error. Existing output directories are refused, including directories created during computation. Input files are unchanged.

## Use an existing STAM store

Supply an ordinary inline native STAM JSON store containing both original and edited text resources, then name their IDs and the note IDs to transfer. No new annotation input schema is needed. Resource text must be inline; external `@include` files are refused before native loading.

Reopen the result through STAM:

```python
import json
from pathlib import Path
from stam import AnnotationStore

ledger = json.loads(Path("result-pinned/review-ledger.json").read_text())
row = next(row for row in ledger["rows"] if row["id"] == "very")
store = AnnotationStore(file="result-pinned/store.stam.json")
note = store.annotation(row["output_note_id"])
for selection in note.textselections():
    print(selection.resource().id(), selection.begin(), selection.end(), selection.text())
```

For an already-loaded store, `from signelet import integrate` exposes `integrate(store, source_id, target_id, note_ids, pins=(), max_band=64, cell_limit=2_000_000)`. It returns an isolated native store and ledger, leaving the caller's store untouched. Safe loading of that original store is the API caller's responsibility.

## Review decisions

The offline page displays selected notes, reasons, native data previews and source/target context. Search and 50-note pages expose the full selected list. Candidate choices are bounded hints; already-agreed positions are not new assumptions. Unknown, unsupported, changed or deleted notes remain visible and may have no eligible pin. Full resource text can be expanded read-only. The page performs no alignment, command execution or network requests.

Decisions bind to the **exact original file bytes**, resource text hashes and stated model. Editing or merely reformatting the input makes the decision stale; generate a new review instead. Import checks strict schema, offsets, baseline pins and current candidate membership before recomputation. Files are unsigned and represent supplied assumptions, not authenticated approval or semantic truth. Keep review pages and decisions private when their input text or note data is private.

## What agreement means

An edit alignment assigns original characters to edited characters or deletions. Signelet considers every global alignment with minimum unit edit cost: matching costs 0; insertion, deletion or substitution costs 1. A certified diagonal band covers every optimal path, not just one chosen path. A note transfers only when every covered character has one agreed destination, the destinations are consecutive, and the exact original text survives.

This is separate from STAM's configurable local/global scoring. Agreement under this model is not semantic truth or a novelty claim. Offsets are **Unicode code points**, not browser UTF-16 units or visible grapheme clusters. Text is not normalized; composed and decomposed characters differ.

## Limits

Only one direct, nonempty, contiguous native `TextSelector` on the stated original resource is supported. Compound or higher-order selectors remain intact and are marked unsupported. Notes spanning an inserted gap are refused. Native data and references are checked after transposition; raw JSON spelling is not a lossless interchange promise.

Inputs are bounded: 4 MiB serialized store, 5,000 selected notes, 100,000 code points / 256 KiB UTF-8 per resource, and 100,000 total selected character coverage. Alignment allows 2,000,000 cumulative alignment-grid cells and band 64 per segment between pins. `--cell-limit` and `--max-band` can lower those limits. Decision JSON is bounded at 4 MiB and nesting depth 32; baseline pins at 2,000. Decision import performs an additional bounded alignment to validate the prior candidate set, then recomputes with the new pin. Data previews and candidate lists are labeled when truncated. Serialization occurs before the API store-size check, so this is not a hard memory ceiling. Large or heavily changed texts may require review because the budget is exhausted.

## Validation

Tests use actual STAM, native store save/reopen, notes/data/provenance, Unicode selections, ambiguity, pins and refusals. Run `python -m unittest discover -s tests -v` after installation; `node --test tests/review-ui.test.mjs` checks code-point display, one-choice export and paging without browser dependencies. CI is configured for Python 3.12 and 3.14 with STAM 0.12.1; the same native cases passed locally on macOS arm64 under Python 3.12.14 and 3.14.7.

Earlier private feasibility checks on macOS arm64, Python 3.12.14 and STAM 0.11.1 used public-domain Alice Chapter I (11,775 code points) and 2,195 self-authored synthetic word notes. A heading insertion transferred all notes; changing the first `Alice` to `Alicia` transferred 2,194 and retained one for review. These controlled cases do not establish user demand or universal performance. The chapter is not bundled; [fixture reconstruction and validation scope](docs/validation.md) give the source, hash, selection method and reuse terms.
