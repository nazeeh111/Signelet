"""Original MIT CLI for an existing inline native STAM store."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import sys
from .adapter import AnnotationStore, integrate, _inline, MAX_STORE_BYTES


def _run(argv=None):
    parser = argparse.ArgumentParser(
        description="Transfer selected STAM notes when every minimum-cost character alignment agrees."
    )
    parser.add_argument("store", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--note", action="append", required=True)
    parser.add_argument("--pin", action="append", default=[], metavar="OLD:NEW")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-band", type=int, default=64)
    parser.add_argument("--cell-limit", type=int, default=2000000)
    parser.add_argument("--version", action="version", version="Signelet 0.1.0")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output destination must not exist")
    with args.store.open("rb") as handle:
        raw = handle.read(MAX_STORE_BYTES + 1)
    if len(raw) > MAX_STORE_BYTES:
        parser.error("inline store exceeds byte budget")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    document = json.loads(raw, object_pairs_hook=unique)
    _inline(document)
    if type(document) is not dict or document.get("@type") != "AnnotationStore":
        raise ValueError("native AnnotationStore JSON required")
    if type(document.get("resources")) is not list or any(
        type(resource) is not dict or type(resource.get("text")) is not str
        for resource in document["resources"]
    ):
        raise ValueError("inline resources with text required")
    # String loading avoids resource filename resolution; external includes are refused first.
    store = AnnotationStore(
        string=raw.decode("utf-8"),
        config={"use_include": False, "strip_temp_ids": False},
    )
    pins = [tuple(int(x) for x in value.split(":")) for value in args.pin]
    output, report = integrate(
        store,
        args.source,
        args.target,
        args.note,
        pins=pins,
        max_band=args.max_band,
        cell_limit=args.cell_limit,
    )
    native = output.to_json_string()
    # Reopen the native serialization before delivery, using the same no-include profile.
    reopened = AnnotationStore(
        string=native, config={"use_include": False, "strip_temp_ids": False}
    )
    for row in report["rows"]:
        reopened.annotation(row["id"])
        if row["status"] == "transposed":
            reopened.annotation(row["output_note_id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="stam-agreement-", dir=args.output.parent
    ) as temp:
        stage = Path(temp) / "result"
        stage.mkdir()
        (stage / "store.stam.json").write_text(native, encoding="utf-8")
        (stage / "review-ledger.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        # Exclusive reservation refuses even an empty directory created during computation.
        args.output.mkdir()
        os.rename(stage / "store.stam.json", args.output / "store.stam.json")
        os.rename(stage / "review-ledger.json", args.output / "review-ledger.json")
    print(
        json.dumps(
            {
                "status": report["status"],
                "counts": report["counts"],
                "output": str(args.output),
            }
        )
    )
    return 0 if report["status"] == "complete" else 1


def main(argv=None):
    try:
        return _run(argv)
    except Exception as error:
        print("signelet: " + str(error), file=sys.stderr)
        return 2
