"""Exercise the installed console script and reopen its real native STAM outputs.

Usage: installed-python tests/installed_smoke.py EXAMPLE [NEW_EVIDENCE_DIRECTORY]
No source imports or PYTHONPATH are needed. The input is self-authored synthetic data.
"""

from importlib import metadata
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import signelet
from stam import AnnotationStore


def run(root, console, *args):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return subprocess.run(
        [str(console), *map(str, args)], cwd=root, env=environment,
        capture_output=True, text=True, check=False,
    )


def data(annotation):
    return [
        (item.dataset().id(), item.key().id(), item.id(), item.value().get())
        for item in annotation.data()
    ]


def reopen(path):
    return AnnotationStore(
        file=str(path), config={"use_include": False, "strip_temp_ids": False},
    )


def verify(root, example):
    console = Path(sys.executable).parent / "signelet"
    assert console.is_file(), console
    assert "site-packages" in str(Path(signelet.__file__).resolve()), signelet.__file__
    assert metadata.version("signelet") == signelet.__version__ == "0.1.0"
    assert metadata.version("stam") == "0.12.1"
    assert "stam==0.12.1" in metadata.requires("signelet")
    version = run(root, console, "--version")
    assert version.returncode == 0 and version.stdout.strip() == "Signelet 0.1.0", version
    original_bytes = example.read_bytes()
    source = root / "input.stam.json"
    source.write_bytes(original_bytes)
    original = reopen(source)
    original_notes = {name: json.loads(original.annotation(name).json()) for name in ("very", "boat")}
    common = [source, "--source", "original", "--target", "edited", "--note", "very", "--note", "boat"]
    results = {}

    def execute(name, expected, *extra):
        result = run(root, console, *common, *extra, "--output", root / name)
        assert result.returncode == expected, (name, result.returncode, result.stdout, result.stderr)
        assert source.read_bytes() == original_bytes
        results[name] = {"exit": result.returncode}
        if expected == 2:
            assert not (root / name).exists()
            return None, None
        ledger = json.loads((root / name / "review-ledger.json").read_text())
        store = reopen(root / name / "store.stam.json")
        assert store.resource("original").text() == original.resource("original").text()
        assert store.resource("edited").text() == original.resource("edited").text()
        for note, expected_note in original_notes.items():
            assert json.loads(store.annotation(note).json()) == expected_note
        for row in ledger["rows"]:
            if row["status"] == "transposed":
                note = store.annotation(row["output_note_id"])
                selections = list(note.textselections())
                assert len(selections) == 1
                selection = selections[0]
                assert selection.resource().id() == "edited"
                assert [selection.begin(), selection.end()] == row["target"]
                assert selection.text() == row["exact"]
                assert data(note) == data(store.annotation(row["id"]))
                assert row["output_note_id"] in row["native_outputs"]
                provenance = [store.annotation(name) for name in row["native_outputs"] if name != row["output_note_id"]]
                assert provenance and any(
                    item.dataset().id() == "https://w3id.org/stam/extensions/stam-transpose/"
                    and item.key().id() == "Transposition"
                    for annotation in provenance for item in annotation.data()
                )
        results[name].update(status=ledger["status"], counts=ledger["counts"], native_reopened=True)
        return ledger, store

    review, _ = execute("review", 1)
    assert review["counts"] == {"transposed": 1, "review": 1, "unknown": 0, "unsupported": 0}
    rows = {row["id"]: row for row in review["rows"]}
    assert rows["very"]["status"] == "review" and rows["boat"]["target"] == [19, 23]
    endpoint = rows["very"]["pin_diagnostics"]["endpoints"][0]
    assert endpoint["source_offset"] == 4
    assert [candidate["target_offset"] for candidate in endpoint["candidates"]] == [4, 9]
    chosen = next(candidate for candidate in endpoint["candidates"] if candidate["target_offset"] == 9 and candidate["equal_character"])
    pin = f"{endpoint['source_offset']}:{chosen['target_offset']}"
    resolved, _ = execute("resolved", 0, "--pin", pin)
    assert resolved["counts"] == {"transposed": 2, "review": 0, "unknown": 0, "unsupported": 0}
    assert {row["id"]: row["target"] for row in resolved["rows"]} == {"very": [9, 13], "boat": [19, 23]}
    unknown, _ = execute("unknown", 1, "--cell-limit", "0")
    assert unknown["counts"] == {"transposed": 0, "review": 0, "unknown": 2, "unsupported": 0}
    assert unknown["pivot_id"] is None
    execute("invalid", 2, "--pin", "14:4")
    occupied = root / "occupied"
    occupied.mkdir()
    sentinel = occupied / "preserve.bin"
    sentinel.write_bytes(b"existing destination must survive\x00\xff")
    before = sentinel.read_bytes()
    inode = occupied.stat().st_ino
    refused = run(root, console, *common, "--pin", pin, "--output", occupied)
    assert refused.returncode == 2, (refused.stdout, refused.stderr)
    assert occupied.stat().st_ino == inode and sentinel.read_bytes() == before
    assert list(occupied.iterdir()) == [sentinel]
    assert source.read_bytes() == example.read_bytes() == original_bytes
    results["destination_preserved"] = {"exit": 2, "unchanged_bytes_and_directory": True}
    evidence = {
        "python": sys.version, "installed_module": str(Path(signelet.__file__).resolve()),
        "console": str(console), "stam_version": metadata.version("stam"),
        "version_output": version.stdout.strip(), "outside_source": True,
        "fixture_sha256": hashlib.sha256(original_bytes).hexdigest(), "ledger_derived_pin": pin,
        "input_unchanged": True, "results": results,
    }
    (root / "installed-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    assert len(sys.argv) in (2, 3), "Provide the native example and optional new evidence directory."
    example = Path(sys.argv[1]).resolve()
    if len(sys.argv) == 3:
        root = Path(sys.argv[2]).resolve()
        root.mkdir(exist_ok=False)
        verify(root, example)
    else:
        with tempfile.TemporaryDirectory(prefix="signelet-installed-") as name:
            verify(Path(name), example)
