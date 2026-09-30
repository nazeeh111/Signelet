"""Tiny exhaustive oracle: enumerate full paths, with no DP or band pruning."""

import itertools
import unittest
from signelet._alignment import align, remap


def full_paths(old, new, pins=()):
    paths = []

    def visit(i, j, cost, mapping):
        if i == len(old) and j == len(new):
            if all(mapping[x] == y for x, y in pins):
                paths.append((cost, tuple(mapping)))
            return
        if i < len(old):
            visit(i + 1, j, cost + 1, mapping + [None])
        if j < len(new):
            visit(i, j + 1, cost + 1, mapping)
        if i < len(old) and j < len(new):
            visit(i + 1, j + 1, cost + (old[i] != new[j]), mapping + [j])

    visit(0, 0, 0, [])
    distance = min(cost for cost, _ in paths)
    return distance, [mapping for cost, mapping in paths if cost == distance]


def pins_for(old, new):
    pairs = [
        (i, j) for i in range(len(old)) for j in range(len(new)) if old[i] == new[j]
    ]
    yield ()
    for count in range(1, min(len(old), len(new)) + 1):
        for selected in itertools.combinations(pairs, count):
            if all(x[0] < y[0] and x[1] < y[1] for x, y in zip(selected, selected[1:])):
                yield selected


class ExhaustiveAlignment(unittest.TestCase):
    def check_model(self, old, new, pins=()):
        distance, best = full_paths(old, new, pins)
        result = align(old, new, pins)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["distance"], distance)
        self.assertEqual(
            result["choices"], [{path[i] for path in best} for i in range(len(old))]
        )
        for start in range(len(old)):
            for end in range(start + 1, len(old) + 1):
                mappings = {path[start:end] for path in best}
                expected = None
                if len(mappings) == 1:
                    mapping = next(iter(mappings))
                    if (
                        None not in mapping
                        and mapping == tuple(range(mapping[0], mapping[-1] + 1))
                        and old[start:end] == new[mapping[0] : mapping[-1] + 1]
                    ):
                        expected = [mapping[0], mapping[-1] + 1]
                row = remap(
                    old, new, [{"id": "note", "start": start, "end": end}], pins
                )["rows"][0]
                self.assertEqual(
                    row.get("target") if row["status"] == "mapped" else None, expected
                )

    def test_every_tiny_binary_pair_and_ordered_equal_pins(self):
        strings = [
            "".join(chars)
            for length in range(3)
            for chars in itertools.product("ab", repeat=length)
        ]
        for old, new in itertools.product(strings, repeat=2):
            for pins in pins_for(old, new):
                with self.subTest(old=old, new=new, pins=pins):
                    self.check_model(old, new, pins)

    def test_unicode_boundaries_and_conditional_repetition(self):
        for old, new, pins in [
            ("😀é", "X😀é", ()),
            ("e\u0301", "Xe\u0301", ()),
            ("é", "e\u0301", ()),
            ("\t\r\n", "X\t\r\n", ()),
            ("a", "aa", ()),
            ("a", "aa", ((0, 1),)),
        ]:
            with self.subTest(old=old, new=new, pins=pins):
                self.check_model(old, new, pins)

    def test_bounded_unknown_is_not_a_partial_choice_certificate(self):
        for limits in [{"cell_limit": 0}, {"max_band": 0}]:
            result = align("ab", "XYZ", **limits)
            self.assertEqual(result["status"], "unknown")
            self.assertNotIn("choices", result)
            self.assertFalse(result.get("certified_all_optimal_paths", False))


if __name__ == "__main__":
    unittest.main()
