"""Original MIT adapter, using GPL-3.0-only STAM as an external dependency.

No upstream code is copied or modified. Certified alignment is the separately
frozen original MIT kernel. STAM owns resources, note data, serialization,
transposition and its existing provenance. This is not STAM's alignment mode.
"""

import hashlib
import json

from stam import AnnotationStore, Selector, Offset
from ._alignment import align, MAX_CHARS, MAX_BYTES

TRANSPOSE = "https://w3id.org/stam/extensions/stam-transpose/"
MAX_STORE_BYTES = 4 * 1024 * 1024
MAX_NOTES = 5000


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _inline(value):
    if type(value) is dict:
        if "@include" in value:
            raise ValueError("external includes unsupported; inline store required")
        for child in value.values():
            _inline(child)
    elif type(value) is list:
        for child in value:
            _inline(child)


def data_values(annotation):
    return [
        {
            "set": item.dataset().id(),
            "key": item.key().id(),
            "id": item.id(),
            "value": item.value().get(),
        }
        for item in annotation.data()
    ]


def _blocks(old, new, choices):
    blocks = []
    for i, options in enumerate(choices):
        if len(options) != 1 or None in options:
            continue
        j = next(iter(options))
        if old[i] != new[j]:
            continue
        if blocks and blocks[-1][1] == i and blocks[-1][3] == j:
            blocks[-1][1] += 1
            blocks[-1][3] += 1
        else:
            blocks.append([i, i + 1, j, j + 1])
    return blocks


def _diagnostics(old, new, s, e, choices):
    """Bounded hints only; endpoint choices need not coexist on a full path."""
    ends = []
    for i in dict.fromkeys([s, e - 1]):
        offsets = sorted(j for j in choices[i] if j is not None)
        ends.append(
            {
                "source_offset": i,
                "source_character": old[i],
                "deletion_possible": None in choices[i],
                "candidate_count": len(offsets),
                "candidate_cap": 8,
                "truncated": len(offsets) > 8,
                "candidates": [
                    {
                        "target_offset": j,
                        "target_character": new[j],
                        "equal_character": old[i] == new[j],
                        "context_start": max(0, j - 12),
                        "context": new[max(0, j - 12) : j + 13],
                    }
                    for j in offsets[:8]
                ],
            }
        )
    return {
        "unit": "Unicode code points",
        "source_range": [s, e],
        "selected_text": old[s : min(e, s + 128)],
        "selected_text_cap": 128,
        "selected_text_truncated": e - s > 128,
        "endpoints": ends,
        "warning": "Endpoint choices may not coexist on one path. Pin one equal character and recompute; certainty is conditional on model and pins.",
    }


def integrate(store, source_id, target_id, note_ids, pins=(), **limits):
    """Return a new native STAM store and diagnostic ledger; caller store untouched.

    Supports direct single contiguous TextSelector notes on source_id. Other
    selectors remain unsupported, preserved and recorded. Every requested note
    receives a status. Unknown alignment creates no new notes or mapping.
    """
    if (
        type(note_ids) not in (tuple, list)
        or len(note_ids) > MAX_NOTES
        or any(type(x) is not str for x in note_ids)
        or len(set(note_ids)) != len(note_ids)
    ):
        raise ValueError("unique bounded note ids required")
    if source_id == target_id:
        raise ValueError("distinct source and target resource ids required")
    source, target = store.resource(source_id), store.resource(target_id)
    old, new = source.text(), target.text()
    if max(len(old), len(new)) > MAX_CHARS:
        raise ValueError("resource code-point budget exceeded")
    if max(len(old.encode("utf-8")), len(new.encode("utf-8"))) > MAX_BYTES:
        raise ValueError("resource byte budget exceeded")
    snapshot = store.to_json_string()
    if len(snapshot) > MAX_STORE_BYTES or len(snapshot.encode()) > MAX_STORE_BYTES:
        raise ValueError("inline store byte budget exceeded")
    _inline(json.loads(snapshot))
    # Isolated native copy avoids any partial mutation of the caller's store.
    working = AnnotationStore(
        string=snapshot, config={"use_include": False, "strip_temp_ids": False}
    )
    original = {name: json.loads(working.annotation(name).json()) for name in note_ids}
    rows = []
    covered = 0
    for name in note_ids:
        annotation = working.annotation(name)
        target_spec = original[name]["target"]
        row = {"id": name, "status": "unsupported"}
        if (
            target_spec.get("@type") != "TextSelector"
            or target_spec.get("resource") != source_id
        ):
            row["reason"] = "requires_direct_single_source_TextSelector"
        else:
            selections = list(annotation.textselections())
            if len(selections) != 1:
                raise ValueError("TextSelector did not produce one selection")
            selection = selections[0]
            s, e = selection.begin(), selection.end()
            if not 0 <= s < e <= len(old):
                row["reason"] = "empty_or_invalid_selection"
            else:
                row.update(status="pending", source=[s, e])
                covered += e - s
        rows.append(row)
    if covered > MAX_CHARS:
        raise ValueError("requested annotation coverage budget exceeded")
    result = align(old, new, pins, **limits)
    blocks = []
    safe = []
    for row in rows:
        if row["status"] != "pending":
            continue
        if result["status"] != "complete":
            row.update(status="unknown", reason=result["reason"])
            continue
        s, e = row["source"]
        options = result["choices"][s:e]
        if not all(len(x) == 1 and None not in x for x in options):
            row["pin_diagnostics"] = _diagnostics(old, new, s, e, result["choices"])
            row.update(
                status="review",
                reason="alignment_ambiguous_or_deleted",
                deletion_possible=any(None in x for x in options),
            )
            continue
        mapped = [next(iter(x)) for x in options]
        begin, end = mapped[0], mapped[-1] + 1
        if mapped != list(range(begin, end)) or old[s:e] != new[begin:end]:
            row["pin_diagnostics"] = _diagnostics(old, new, s, e, result["choices"])
            row.update(
                status="review",
                reason="text_changed_or_noncontiguous",
                proposed_target=[begin, end],
            )
            continue
        row.update(status="certified", target=[begin, end], exact=new[begin:end])
        safe.append(row)
    pivot = None
    if result["status"] == "complete" and safe:
        blocks = _blocks(old, new, result["choices"])
        reserved = {a.id() for a in working.annotations()}
        seed = _digest(
            snapshot.encode()
            + json.dumps(
                [source_id, target_id, list(pins), limits], sort_keys=True
            ).encode()
        )[:20]
        prefix = "agreement-" + seed
        counter = 0
        while any(
            name in reserved
            for name in [prefix + "-source", prefix + "-target", prefix + "-pivot"]
        ):
            counter += 1
            prefix = "agreement-" + seed + "-" + str(counter)
        source, target = working.resource(source_id), working.resource(target_id)
        # Public STAM API constructs the standard Transposition model; no Rust code copied.
        left = working.annotate(
            id=prefix + "-source",
            target=Selector.directionalselector(
                *[
                    Selector.textselector(source, Offset.simple(s, e))
                    for s, e, _, _ in blocks
                ]
            ),
            data={"set": TRANSPOSE, "key": "TranspositionSide", "value": None},
        )
        right = working.annotate(
            id=prefix + "-target",
            target=Selector.directionalselector(
                *[
                    Selector.textselector(target, Offset.simple(s, e))
                    for _, _, s, e in blocks
                ]
            ),
            data={"set": TRANSPOSE, "key": "TranspositionSide", "value": None},
        )
        pivot = working.annotate(
            id=prefix + "-pivot",
            target=Selector.directionalselector(
                Selector.annotationselector(left), Selector.annotationselector(right)
            ),
            data={"set": TRANSPOSE, "key": "Transposition", "value": None},
        )
        for row in safe:
            source_note = working.annotation(row["id"])
            outputs = list(source_note.transpose(pivot))
            destination = [
                a
                for a in outputs
                if json.loads(a.json())["target"].get("@type") == "TextSelector"
                and json.loads(a.json())["target"].get("resource") == target_id
            ]
            if len(destination) != 1:
                raise RuntimeError(
                    "native transpose did not return one direct target note"
                )
            transferred = destination[0]
            selection = list(transferred.textselections())[0]
            if [selection.begin(), selection.end()] != row[
                "target"
            ] or selection.text() != row["exact"]:
                raise RuntimeError("native transpose disagrees with certified target")
            if data_values(transferred) != data_values(source_note):
                raise RuntimeError("native note data changed")
            row.update(
                status="transposed",
                output_note_id=transferred.id(),
                native_outputs=[a.id() for a in outputs],
            )
    for name, expected in original.items():
        if json.loads(working.annotation(name).json()) != expected:
            raise RuntimeError("original note changed")
    if store.to_json_string() != snapshot:
        raise RuntimeError("caller store changed")
    report = {
        "status": "complete"
        if all(row["status"] == "transposed" for row in rows)
        else "review_required",
        "source_id": source_id,
        "target_id": target_id,
        "source_sha256": _digest(old.encode()),
        "target_sha256": _digest(new.encode()),
        "input_store_sha256": _digest(snapshot.encode()),
        "alignment": {k: v for k, v in result.items() if k != "choices"},
        "model": "raw Unicode code points; global match0/substitution1/insertion1/deletion1; conditional pins",
        "native_alignment_called": False,
        "pivot_id": None if pivot is None else pivot.id(),
        "certified_blocks": blocks,
        "rows": rows,
        "counts": {
            status: sum(row["status"] == status for row in rows)
            for status in ["transposed", "review", "unknown", "unsupported"]
        },
        "caller_unchanged": True,
        "original_notes_retained": True,
    }
    return working, report
