# Dependency and lineage

Signelet's original adapter, edit-alignment kernel, CLI, tests and self-authored examples are MIT licensed. It requires the external `stam==0.12.1` Python package, which is GPL-3.0-only. STAM is not bundled or relicensed by this project. The original-source MIT license does not make STAM or a combined distribution MIT-only. Any redistribution involving STAM must retain and satisfy its license terms.

STAM supplies annotation resources/data, native serialization, transposition and existing provenance. Signelet supplies a separate conservative agreement policy under a fixed raw-codepoint, global, unit-cost edit model. It is not a replacement annotation engine and does not reinterpret STAM's configurable alignment scores. No upstream STAM code was copied or modified.

Primary sources: [STAM project](https://annotation.github.io/stam), [STAM tools native alignment implementation](https://github.com/annotation/stam-tools/blob/c947e20ad0aa78a1f992b51b80db4bac957ff39f/src/align.rs), [GPL license](https://github.com/annotation/stam-tools/blob/c947e20ad0aa78a1f992b51b80db4bac957ff39f/LICENSE).
