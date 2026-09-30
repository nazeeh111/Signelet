import test from "node:test";
import assert from "node:assert/strict";
import {
  textParts,
  notePage,
  makeDecision,
  candidateKind,
  contextWindow,
} from "../src/signelet/assets/review.mjs";

// A UTF-16 slice would shift or split selections after an emoji.
test("context highlighting uses code points across emoji, combining marks and CRLF", () => {
  assert.deepEqual(textParts("🙂The very blue boat.", 5, 9), {
    before: "🙂The ",
    selected: "very",
    after: " blue boat.",
  });
  assert.deepEqual(textParts("e\u0301\r\n🙂x", 1, 5), {
    before: "e",
    selected: "\u0301\r\n🙂",
    after: "x",
  });
  const window = contextWindow(
    Array.from("🙂The very very blue boat."),
    10,
    11,
  );
  assert.equal(window.selected, "v");
  assert.equal(window.before, "🙂The very ");
  assert.equal(window.startOffset, 0);
});

// Invalid ranges must not silently select unrelated text.
test("context highlighting rejects out-of-range and reversed positions", () => {
  for (const [start, end] of [
    [-1, 1],
    [2, 1],
    [0, 4],
    [0.5, 1],
  ])
    assert.throws(() => textParts("abc", start, end), RangeError);
});

// Large selections must stay bounded and disclose omitted selection text.
test("context bounds long text without pretending its truncated selection is complete", () => {
  const parts = contextWindow("x".repeat(2000), 700, 1700);
  assert.equal(parts.before.length, 40);
  assert.equal(parts.selected.length, 128);
  assert.equal(parts.after, "");
  assert.equal(parts.selectionTruncated, true);
  assert.equal(parts.startOffset, 660);
});

// Rendering every requested note would defeat the 5000-note bound in the UI.
test("note paging searches all notes and clamps page after filtering", () => {
  const rows = Array.from({ length: 5000 }, (_, i) => ({
    id: `note-${i}`,
    selected_text: i === 4999 ? "needle" : "",
  }));
  assert.equal(notePage(rows, "", 0).rows.length, 50);
  assert.equal(notePage(rows, "", 99).rows[49].id, "note-4999");
  const result = notePage(rows, "NEEDLE", 99);
  assert.equal(result.total, 1);
  assert.equal(result.page, 0);
  assert.equal(result.rows[0].id, "note-4999");
  assert.equal(notePage(rows, "note-4999", 0).rows[0].id, "note-4999");
});

const fixture = {
  binding: {
    schema: "signelet-review-decision-v1",
    model: "signelet-unit-codepoint-v1",
    input_file_sha256:
      "1cd35c6251c3b7beef559abf4a7acb773ca157012db3db4584df3ed1c7fbac21",
    source_id: "original",
    target_id: "edited",
    source_sha256:
      "a6b8c1b070fa98f9bcc807d4bbbe4528ee120d11087772fc6cfe10ea557abc19",
    target_sha256:
      "88d6f5e616310c58125d701d7a49637bd27b8df028d2f4c58414d1f8dd0f8c46",
    note_ids: ["very", "boat"],
    limits: {
      max_band: 64,
      cell_limit: 2000000,
    },
    base_pins: [],
  },
  source_text: "The very blue boat.",
  target_text: "The very very blue boat.",
  unit: "Unicode code points",
  counts: {
    transposed: 1,
    review: 1,
    unknown: 0,
    unsupported: 0,
  },
  rows: [
    {
      id: "very",
      status: "review",
      reason: "alignment_ambiguous_or_deleted",
      source: [4, 8],
      target: null,
      selected_text: "very",
      selected_text_truncated: false,
      data_preview: "self-authored note very",
      data_preview_truncated: false,
      endpoints: [
        {
          source_offset: 4,
          deletion_possible: false,
          candidate_count: 2,
          candidate_cap: 8,
          truncated: false,
          candidates: [
            {
              target_offset: 4,
              eligible: true,
            },
            {
              target_offset: 9,
              eligible: true,
            },
          ],
        },
        {
          source_offset: 7,
          deletion_possible: false,
          candidate_count: 2,
          candidate_cap: 8,
          truncated: false,
          candidates: [
            {
              target_offset: 7,
              eligible: true,
            },
            {
              target_offset: 12,
              eligible: true,
            },
          ],
        },
      ],
    },
    {
      id: "boat",
      status: "transposed",
      reason: null,
      source: [14, 18],
      target: [19, 23],
      selected_text: "boat",
      selected_text_truncated: false,
      data_preview: "self-authored note boat",
      data_preview_truncated: false,
      endpoints: [],
    },
  ],
};
// Export must preserve binding and native results, without inventing a target span.
test("decision exports exactly one eligible pin while preserving prior pins and statuses", () => {
  const payload = structuredClone(fixture);
  payload.binding.base_pins = [[0, 0]];
  const prior = structuredClone(payload);
  const decision = makeDecision(payload, {
    note_id: "very",
    source_offset: 4,
    target_offset: 9,
  });
  assert.deepEqual(decision.choice, {
    note_id: "very",
    source_offset: 4,
    target_offset: 9,
  });
  assert.deepEqual(decision.base_pins, [[0, 0]]);
  assert.deepEqual(
    Object.keys(decision).sort(),
    [...Object.keys(payload.binding), "choice"].sort(),
  );
  assert.deepEqual(payload, prior);
  assert.equal(payload.rows[0].status, "review");
  assert.equal(payload.counts.review, 1);
});

// Unknown, non-equal and non-recorded candidates cannot become browser decisions.
test("decision rejects unsupported choices and browser-side edits to eligibility", () => {
  for (const choice of [
    null,
    { note_id: "boat", source_offset: 14, target_offset: 19 },
    { note_id: "very", source_offset: 4, target_offset: 10 },
    { note_id: "very", source_offset: 3, target_offset: 9 },
  ]) {
    assert.throws(() => makeDecision(fixture, choice));
  }
  const altered = structuredClone(fixture);
  altered.rows[0].endpoints[0].candidates[1].eligible = false;
  assert.throws(() =>
    makeDecision(altered, {
      note_id: "very",
      source_offset: 4,
      target_offset: 9,
    }),
  );
  altered.rows[0].endpoints[0].candidates[1].eligible = true;
  altered.target_text = "The xxxx very blue boat.";
  assert.throws(() =>
    makeDecision(altered, {
      note_id: "very",
      source_offset: 4,
      target_offset: 4,
    }),
  );
});

// Equal endpoints around an inserted gap are already agreed and cannot resolve the span.
test("already-agreed gap endpoints remain diagnostic even if eligibility is misreported", () => {
  const endpoint = {
    source_offset: 0,
    candidate_count: 1,
    deletion_possible: false,
    candidates: [{ target_offset: 0, eligible: false }],
  };
  assert.equal(
    candidateKind(endpoint, endpoint.candidates[0], "a", "a"),
    "agreed",
  );
  const gap = structuredClone(fixture);
  gap.source_text = "ab";
  gap.target_text = "aXb";
  gap.rows[0].source = [0, 2];
  gap.rows[0].endpoints = [endpoint];
  assert.throws(() =>
    makeDecision(gap, { note_id: "very", source_offset: 0, target_offset: 0 }),
  );
  endpoint.candidates[0].eligible = true;
  gap.rows[0].endpoints = [endpoint];
  assert.equal(
    candidateKind(endpoint, endpoint.candidates[0], "a", "a"),
    "agreed",
  );
  assert.throws(() =>
    makeDecision(gap, { note_id: "very", source_offset: 0, target_offset: 0 }),
  );
});
