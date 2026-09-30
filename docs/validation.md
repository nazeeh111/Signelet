# Validation scope

The installed package checks use actual `stam==0.12.1`: selected native note outcomes, data references/values, existing provenance, native JSON reopen, Unicode codepoint offsets, CLI exit codes, pin recomputation, bounded unknown and new-output preservation. Local native checks used macOS arm64, CPython 3.12.14 and 3.14.7. CI configuration is not evidence of a completed remote CI run.

Earlier chapter measurements used CPython 3.12.14 and STAM 0.11.1 on the same platform, before packaging. They are controlled feasibility results, not a benchmark across platforms or user study:

| Edit | Synthetic notes | Transferred | Review |
| --- | ---: | ---: | ---: |
| Prefix `Editorial heading 😀\n` | 2,195 | 2,195 | 0 |
| First `Alice` replaced with `Alicia` | 2,195 | 2,194 | 1 |

For the exact corpus, use Project Gutenberg's [UTF-8 edition 11](https://www.gutenberg.org/ebooks/11.txt.utf-8), retaining CRLF rather than normalizing newlines. Select the body beginning `CHAPTER I.\r\nDown the Rabbit-Hole\r\n` and ending immediately before Chapter II. Verify 11,775 Unicode code points and SHA-256 `1e507cd2154adbde78465fb8d8ed7ef6d5b112e8a7570a0915acbc592bd6e10a`. A changed edition or different extraction will not reproduce this fixture.

Select every match of Python `re.finditer(r'\w+', chapter)` and attach a self-authored string note to each resulting native TextSelector. The counts include the chapter heading and split words at apostrophes. Create the edited native text resource using either exact edit above, request every note ID, then reopen the serialized native store and check every original plus transferred range, text and native data. Bodies are synthetic; no private notes were acquired. The chapter is not bundled. Consult [Gutenberg's source and reuse terms](https://www.gutenberg.org/ebooks/11) for the text.

The shipped `tests/test_alignment.py` provides a reproducible independent oracle: it enumerates every full edit path for all binary strings up to length two and all ordered equal-character pins, then compares the minimum cost, every character's possible destinations and annotation outcomes with the kernel. It uses no alignment-grid algorithm or band pruning. Separate cases cover emoji, combining marks, CRLF, repetition and bounded unknown. These small deterministic checks protect regressions; they do not establish universal implementation correctness. The band certificate covers all optimal paths under the stated unit-cost model, not semantic interpretations.
