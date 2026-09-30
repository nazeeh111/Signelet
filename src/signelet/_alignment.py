"""Raw Unicode code-point edit alignment retaining every globally optimal choice.

Certificate: if a band +/-k contains an endpoint path of cost d <= k,
every globally optimal unit-cost edit path is in this band. Every visited
vertex obeys |i-j| <= number of paid indels <= total path cost <= d.
No greedy prefix/suffix trimming: repetitions can make their alignment ambiguous.
"""

from array import array
import hashlib

MAX_BYTES = 256 * 1024
MAX_CHARS = 100_000
MAX_CELLS = 2_000_000
MAX_BAND = 64


def _one(a, b, max_band, remaining):
    n, m = len(a), len(b)
    k = abs(n - m)
    spent = 0
    if k > max_band:
        return {"status": "unknown", "reason": "edit_budget", "cells": 0}
    while True:
        lows = [max(0, i - k) for i in range(n + 1)]
        highs = [min(m, i + k) for i in range(n + 1)]
        offsets = [0]
        for lo, hi in zip(lows, highs):
            offsets.append(offsets[-1] + hi - lo + 1)
        cells = offsets[-1]
        # Reserve both matrices before allocating; failed bands only spend forward cells.
        if spent + 2 * cells > remaining:
            return {
                "status": "unknown",
                "reason": "cell_budget",
                "cells": spent,
                "next_required_cells": 2 * cells,
                "band": k,
            }
        inf = k + 1
        forward = array("I", [inf]) * cells

        def get(matrix, i, j):
            if i < 0 or i > n or j < lows[i] or j > highs[i]:
                return inf
            return matrix[offsets[i] + j - lows[i]]

        for i in range(n + 1):
            for j in range(lows[i], highs[i] + 1):
                p = offsets[i] + j - lows[i]
                if i == 0:
                    forward[p] = min(j, inf)
                elif j == 0:
                    forward[p] = min(i, inf)
                else:
                    forward[p] = min(
                        inf,
                        get(forward, i - 1, j) + 1,
                        get(forward, i, j - 1) + 1,
                        get(forward, i - 1, j - 1) + (a[i - 1] != b[j - 1]),
                    )
        spent += cells
        distance = get(forward, n, m)
        if distance <= k:
            break
        if k == max_band:
            return {
                "status": "unknown",
                "reason": "edit_budget",
                "cells": spent,
                "band": k,
            }
        k = min(max_band, max(1, k * 2))
    reverse = array("I", [inf]) * cells
    for i in range(n, -1, -1):
        for j in range(highs[i], lows[i] - 1, -1):
            p = offsets[i] + j - lows[i]
            if i == n:
                reverse[p] = min(m - j, inf)
            elif j == m:
                reverse[p] = min(n - i, inf)
            else:
                reverse[p] = min(
                    inf,
                    get(reverse, i + 1, j) + 1,
                    get(reverse, i, j + 1) + 1,
                    get(reverse, i + 1, j + 1) + (a[i] != b[j]),
                )
    spent += cells
    choices = [set() for _ in a]
    for i in range(n):
        for j in range(lows[i], highs[i] + 1):
            f = get(forward, i, j)
            if f + 1 + get(reverse, i + 1, j) == distance:
                choices[i].add(None)
            if j < m and f + (a[i] != b[j]) + get(reverse, i + 1, j + 1) == distance:
                choices[i].add(j)
    return {
        "status": "complete",
        "distance": distance,
        "choices": choices,
        "cells": spent,
        "band": k,
        "certified_all_optimal_paths": True,
        "final_matrix_cells": cells,
    }


def align(a, b, pins=(), *, max_band=MAX_BAND, cell_limit=MAX_CELLS):
    """Align raw code points under the fixed unit-cost model; remap validates UTF-8 inputs."""
    if type(max_band) is not int or not 0 <= max_band <= MAX_BAND:
        raise ValueError("max_band outside bounded profile")
    if type(cell_limit) is not int or not 0 <= cell_limit <= MAX_CELLS:
        raise ValueError("cell_limit outside bounded profile")
    if len(a) > MAX_CHARS or len(b) > MAX_CHARS:
        return {"status": "unknown", "reason": "input_budget", "cells": 0}
    if type(pins) not in (tuple, list) or len(pins) > 2000:
        raise ValueError("invalid pins")
    previous = (-1, -1)
    fixed = []
    for pair in pins:
        if (
            type(pair) not in (tuple, list)
            or len(pair) != 2
            or any(type(x) is not int for x in pair)
        ):
            raise ValueError("pins require two character indices")
        i, j = pair
        if not previous[0] < i < len(a) or not previous[1] < j < len(b) or a[i] != b[j]:
            raise ValueError("pins crossed, contradictory, unequal or out of range")
        fixed.append((i, j))
        previous = (i, j)
    previous = (-1, -1)
    choices = [set() for _ in a]
    spent = distance = 0
    segments = []
    for i, j in [*fixed, (len(a), len(b))]:
        left, right = previous[0] + 1, previous[1] + 1
        segment = _one(a[left:i], b[right:j], max_band, cell_limit - spent)
        spent += segment["cells"]
        if segment["status"] == "unknown":
            return {k: v for k, v in segment.items() if k != "cells"} | {
                "cells": spent,
                "completed_segments": len(segments),
            }
        distance += segment["distance"]
        for x, options in enumerate(segment["choices"], left):
            choices[x] = {None if y is None else y + right for y in options}
        segments.append({k: v for k, v in segment.items() if k != "choices"})
        if i < len(a):
            choices[i] = {j}
        previous = (i, j)
    return {
        "status": "complete",
        "distance": distance,
        "choices": choices,
        "cells": spent,
        "segments": segments,
        "pins": [list(x) for x in fixed],
        "certified_all_optimal_paths": True,
    }


def remap(old, new, annotations, pins=(), **kwargs):
    if type(old) is not str or type(new) is not str:
        raise ValueError("text must be str")
    if type(annotations) is not list or len(annotations) > 2000:
        raise ValueError("bounded annotation list required")
    # Refuse oversized strings before allocating UTF-8 encodings or traversing notes.
    if max(len(old), len(new)) > MAX_CHARS:
        return {"status": "unknown", "reason": "input_budget", "cells": 0}
    covered = 0
    for note in annotations:
        if (
            type(note) is not dict
            or set(note) != {"id", "start", "end"}
            or type(note["id"]) is not str
            or len(note["id"]) > 128
        ):
            raise ValueError("invalid annotation")
        s, e = note["start"], note["end"]
        if type(s) is not int or type(e) is not int or not 0 <= s < e <= len(old):
            raise ValueError("invalid code-point span")
        covered += e - s
    if (
        covered > MAX_CHARS
        or max(len(old.encode("utf-8")), len(new.encode("utf-8"))) > MAX_BYTES
    ):
        return {"status": "unknown", "reason": "input_budget", "cells": 0}
    result = align(old, new, pins, **kwargs)
    if result["status"] != "complete":
        return result
    rows = []
    for note in annotations:
        s, e = note["start"], note["end"]
        options = result["choices"][s:e]
        row = {"id": note["id"], "source": [s, e], "status": "review"}
        if all(len(x) == 1 and None not in x for x in options):
            mapped = [next(iter(x)) for x in options]
            start, end = mapped[0], mapped[-1] + 1
            if mapped == list(range(start, end)) and old[s:e] == new[start:end]:
                row.update(status="mapped", target=[start, end], exact=new[start:end])
            else:
                row.update(reason="text_changed", proposed_target=[start, end])
        else:
            row.update(
                reason="alignment_ambiguous_or_deleted",
                uncertain_codepoints=sum(len(x) != 1 or None in x for x in options),
                first_character_choices=sorted(x for x in options[0] if x is not None),
                last_character_choices=sorted(x for x in options[-1] if x is not None),
                deletion_possible=any(None in x for x in options),
            )
        rows.append(row)
    return {k: v for k, v in result.items() if k != "choices"} | {
        "rows": rows,
        "source_sha256": hashlib.sha256(old.encode()).hexdigest(),
        "target_sha256": hashlib.sha256(new.encode()).hexdigest(),
        "model": "raw_unicode_codepoint_match0_substitute1_insert1_delete1",
    }
