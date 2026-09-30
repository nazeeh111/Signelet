import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from signelet import cli, __version__
from signelet.adapter import AnnotationStore
from test_native import fixture


class InstalledCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input.stam.json"
        self.input.write_text(
            fixture(
                "The very blue boat.",
                "The very very blue boat.",
                [("very", 4, 8), ("boat", 14, 18)],
            ).to_json_string()
        )
        self.before = self.input.read_bytes()
        self.args = [
            str(self.input),
            "--source",
            "old",
            "--target",
            "new",
            "--note",
            "very",
            "--note",
            "boat",
        ]

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, name, *extra):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "signelet",
                *self.args,
                *extra,
                "--output",
                str(self.root / name),
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def test_review_then_reported_pin_and_native_reopen(self):
        review = self.run_cli("review")
        self.assertEqual(review.returncode, 1, review.stderr)
        ledger = json.loads((self.root / "review/review-ledger.json").read_text())
        first = ledger["rows"][0]["pin_diagnostics"]["endpoints"][0]
        self.assertEqual([c["target_offset"] for c in first["candidates"]], [4, 9])
        selected = next(
            c
            for c in first["candidates"]
            if c["target_offset"] == 9 and c["equal_character"]
        )
        pin = f"{first['source_offset']}:{selected['target_offset']}"
        pinned = self.run_cli("pinned", "--pin", pin)
        self.assertEqual(pinned.returncode, 0, pinned.stderr)
        ledger = json.loads((self.root / "pinned/review-ledger.json").read_text())
        reopened = AnnotationStore(file=str(self.root / "pinned/store.stam.json"))
        selection = list(
            reopened.annotation(ledger["rows"][0]["output_note_id"]).textselections()
        )[0]
        self.assertEqual(
            (selection.begin(), selection.end(), selection.text()), (9, 13, "very")
        )
        self.assertEqual(self.input.read_bytes(), self.before)

    def test_unknown_has_ledger_and_exit_one(self):
        result = self.run_cli("unknown", "--cell-limit", "0")
        self.assertEqual(result.returncode, 1, result.stderr)
        ledger = json.loads((self.root / "unknown/review-ledger.json").read_text())
        self.assertEqual(ledger["counts"]["unknown"], 2)
        self.assertIsNone(ledger["pivot_id"])
        self.assertEqual(self.input.read_bytes(), self.before)

    def test_include_and_invalid_pin_leave_input_and_no_output(self):
        result = self.run_cli("bad-pin", "--pin", "14:4")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "bad-pin").exists())
        self.assertEqual(self.input.read_bytes(), self.before)
        raw = b'{"@type":"AnnotationStore","@include":"not-an-allowed-source"}'
        self.input.write_bytes(raw)
        result = self.run_cli("include")
        self.assertEqual(result.returncode, 2)
        self.assertIn("includes unsupported", result.stderr)
        self.assertFalse((self.root / "include").exists())
        self.assertEqual(self.input.read_bytes(), raw)

    def test_new_output_reservation_preserves_competing_empty_directory(self):
        destination = self.root / "race"
        original = cli.integrate
        state = {}

        def competing_directory(*args, **kwargs):
            result = original(*args, **kwargs)
            destination.mkdir()
            state["inode"] = destination.stat().st_ino
            return result

        with patch.object(cli, "integrate", side_effect=competing_directory):
            self.assertEqual(cli.main([*self.args, "--output", str(destination)]), 2)
        self.assertEqual(destination.stat().st_ino, state["inode"])
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(self.input.read_bytes(), self.before)

    def test_help_and_version_without_store(self):
        for option in ["--help", "--version"]:
            result = subprocess.run(
                [sys.executable, "-m", "signelet", option],
                cwd=self.root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout)
        self.assertEqual(f"Signelet {__version__}", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
