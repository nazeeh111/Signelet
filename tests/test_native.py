"""Actual native STAM integration checks; does not retest frozen alignment oracle."""

import json
import unittest
from signelet.adapter import (
    AnnotationStore,
    Selector,
    Offset,
    integrate,
    data_values,
    TRANSPOSE,
)


def fixture(old, new, spans):
    store = AnnotationStore(
        id="fixture", config={"use_include": False, "strip_temp_ids": False}
    )
    source = store.add_resource(id="old", text=old)
    store.add_resource(id="new", text=new)
    dataset = store.add_dataset(id="notes")
    for index, (name, s, e) in enumerate(spans):
        data = dataset.add_data("body", "self-authored note " + name, id="data-" + name)
        store.annotate(
            id=name,
            target=Selector.textselector(source, Offset.simple(s, e)),
            data=data,
        )
    return store


def roundtrip(store):
    return AnnotationStore(
        string=store.to_json_string(),
        config={"use_include": False, "strip_temp_ids": False},
    )


class NativeIntegration(unittest.TestCase):
    def test_safe_ambiguous_and_pin(self):
        original = fixture(
            "The very blue boat.",
            "The very very blue boat.",
            [("very", 4, 8), ("boat", 14, 18)],
        )
        saved = original.to_json_string()
        output, ledger = integrate(original, "old", "new", ["very", "boat"])
        self.assertEqual(
            ledger["counts"],
            {"transposed": 1, "review": 1, "unknown": 0, "unsupported": 0},
        )
        self.assertEqual(original.to_json_string(), saved)
        output = roundtrip(output)
        boat = ledger["rows"][1]
        note = output.annotation(boat["output_note_id"])
        selection = list(note.textselections())[0]
        self.assertEqual(
            (selection.begin(), selection.end(), selection.text()), (19, 23, "boat")
        )
        self.assertEqual(data_values(note), data_values(output.annotation("boat")))
        self.assertEqual(
            json.loads(output.annotation("very").json()),
            json.loads(original.annotation("very").json()),
        )
        self.assertEqual(len(boat["native_outputs"]), 2)
        provenance = output.annotation(
            next(x for x in boat["native_outputs"] if x != boat["output_note_id"])
        )
        self.assertTrue(
            any(
                item.dataset().id() == TRANSPOSE and item.key().id() == "Transposition"
                for item in provenance.data()
            )
        )
        output, pinned = integrate(
            original, "old", "new", ["very", "boat"], pins=[(4, 9)]
        )
        self.assertEqual(pinned["counts"]["transposed"], 2)
        self.assertEqual(pinned["rows"][0]["target"], [9, 13])
        self.assertEqual(original.to_json_string(), saved)

    def test_deleted_changed_gap_and_unknown(self):
        for old, new, reason in [
            ("boat", "boot", "text_changed_or_noncontiguous"),
            ("boat", "", "alignment_ambiguous_or_deleted"),
            ("ab", "aXb", "text_changed_or_noncontiguous"),
        ]:
            store = fixture(old, new, [("note", 0, len(old))])
            output, ledger = integrate(store, "old", "new", ["note"])
            self.assertEqual(ledger["rows"][0]["status"], "review")
            self.assertEqual(ledger["rows"][0]["reason"], reason)
            self.assertIsNone(ledger["pivot_id"])
            self.assertEqual(output.to_json_string(), store.to_json_string())
        store = fixture("boat", "A boat.", [("note", 0, 4)])
        output, ledger = integrate(store, "old", "new", ["note"], cell_limit=0)
        self.assertEqual(ledger["rows"][0]["status"], "unknown")
        self.assertIsNone(ledger["pivot_id"])
        self.assertEqual(output.to_json_string(), store.to_json_string())

    def test_unsupported_native_selector_preserved(self):
        store = fixture("abc def", "X abc def", [("note", 0, 3)])
        source = store.resource("old")
        store.annotate(
            id="composite",
            target=Selector.directionalselector(
                Selector.textselector(source, Offset.simple(0, 3)),
                Selector.textselector(source, Offset.simple(4, 7)),
            ),
            data={"set": "notes", "key": "body", "value": "two spans"},
        )
        before = json.loads(store.annotation("composite").json())
        output, ledger = integrate(store, "old", "new", ["composite", "note"])
        self.assertEqual(ledger["counts"]["unsupported"], 1)
        self.assertEqual(ledger["counts"]["transposed"], 1)
        self.assertEqual(json.loads(output.annotation("composite").json()), before)

    def test_character_boundaries_whitespace_and_emoji(self):
        old = "boat. \U0001f600e\u0301\r\n"
        new = "Heading\n" + old
        store = fixture(
            old,
            new,
            [
                ("word", 0, 4),
                ("space", 5, 6),
                ("emoji", 6, 7),
                ("combining", 8, 9),
                ("crlf", 9, 11),
            ],
        )
        output, ledger = integrate(
            store, "old", "new", ["word", "space", "emoji", "combining", "crlf"]
        )
        self.assertEqual(ledger["counts"]["transposed"], 5)
        for row in ledger["rows"]:
            selection = list(
                roundtrip(output).annotation(row["output_note_id"]).textselections()
            )[0]
            self.assertEqual(selection.text(), old[slice(*row["source"])])
            self.assertEqual(
                [selection.begin(), selection.end()], [x + 8 for x in row["source"]]
            )

    def test_invalid_inputs_leave_caller_unchanged(self):
        store = fixture("a a", "a a", [("note", 0, 1)])
        before = store.to_json_string()
        for names, pins in [
            (["note", "note"], ()),
            (["missing"], ()),
            (["note"], [(2, 0), (0, 2)]),
        ]:
            with self.assertRaises(Exception):
                integrate(store, "old", "new", names, pins=pins)
            self.assertEqual(store.to_json_string(), before)


if __name__ == "__main__":
    unittest.main()
