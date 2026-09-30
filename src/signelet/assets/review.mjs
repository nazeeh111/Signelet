function points(text) {
  return Array.isArray(text) ? text : Array.from(text);
}
function range(chars, start, end) {
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    end > chars.length
  ) {
    throw new RangeError("Invalid code point range.");
  }
}
export function textParts(text, start, end) {
  const chars = points(text);
  range(chars, start, end);
  return {
    before: chars.slice(0, start).join(""),
    selected: chars.slice(start, end).join(""),
    after: chars.slice(end).join(""),
  };
}
export function contextWindow(text, start, end) {
  const chars = points(text);
  range(chars, start, end);
  const left = Math.max(0, start - 40),
    shownEnd = Math.min(end, start + 128);
  return {
    startOffset: left,
    before: chars.slice(left, start).join(""),
    selected: chars.slice(start, shownEnd).join(""),
    after: shownEnd < end ? "" : chars.slice(end, end + 40).join(""),
    selectionTruncated: shownEnd < end,
    beforeTruncated: left > 0,
    afterTruncated: shownEnd < end || end + 40 < chars.length,
  };
}
export function notePage(rows, query, page) {
  const q = query.trim().toLowerCase();
  const matches = q
    ? rows.filter((row) =>
        `${row.id}\n${row.selected_text}`.toLowerCase().includes(q),
      )
    : rows;
  const pages = Math.max(1, Math.ceil(matches.length / 50));
  const index = Math.max(
    0,
    Math.min(pages - 1, Number.isInteger(page) ? page : 0),
  );
  return {
    rows: matches.slice(index * 50, index * 50 + 50),
    total: matches.length,
    page: index,
    pages,
  };
}
export function candidateKind(
  endpoint,
  candidate,
  sourceCharacter,
  targetCharacter,
) {
  if (
    endpoint.candidate_count === 1 &&
    !endpoint.deletion_possible &&
    sourceCharacter === targetCharacter
  )
    return "agreed";
  return candidate.eligible === true && sourceCharacter === targetCharacter
    ? "eligible"
    : "unavailable";
}
export function makeDecision(payload, choice) {
  if (
    !choice ||
    !Number.isInteger(choice.source_offset) ||
    !Number.isInteger(choice.target_offset)
  )
    throw new Error("Choose an eligible character.");
  const row = payload.rows.find((row) => row.id === choice.note_id);
  const endpoint =
    row?.status === "review" &&
    row.endpoints.find(
      (endpoint) => endpoint.source_offset === choice.source_offset,
    );
  const candidate =
    endpoint &&
    endpoint.candidates.find(
      (candidate) =>
        candidate.target_offset === choice.target_offset &&
        candidate.eligible === true,
    );
  const source = points(payload.source_text),
    target = points(payload.target_text);
  if (
    !candidate ||
    (endpoint.candidate_count <= 1 && !endpoint.deletion_possible) ||
    choice.source_offset < 0 ||
    choice.target_offset < 0 ||
    choice.source_offset >= source.length ||
    choice.target_offset >= target.length ||
    source[choice.source_offset] !== target[choice.target_offset]
  )
    throw new Error("This character is not an eligible recorded choice.");
  return {
    ...payload.binding,
    choice: {
      note_id: choice.note_id,
      source_offset: choice.source_offset,
      target_offset: choice.target_offset,
    },
  };
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function character(char) {
  const names = {
    " ": "SPACE",
    "\n": "LINE FEED",
    "\r": "CARRIAGE RETURN",
    "\t": "TAB",
  };
  const hex = char.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
  return `${names[char] || `“${char}”`} · U+${hex}`;
}
const statusName = {
  transposed: "Transferred",
  review: "Review",
  unknown: "Unknown",
  unsupported: "Unsupported",
};

export function initializeReview(payload, app) {
  const source = Array.from(payload.source_text),
    target = Array.from(payload.target_text);
  let selected = payload.rows[0]?.id,
    pending = null,
    query = "",
    page = 0;
  const header = element("header", undefined, "review-header");
  header.append(
    element("p", "Signelet / Annotation review", "eyebrow"),
    element("h1", "Review a character correspondence"),
  );
  header.append(
    element(
      "p",
      `${payload.binding.source_id} → ${payload.binding.target_id}`,
      "resource-route",
    ),
  );
  const counts = element(
    "p",
    Object.entries(payload.counts)
      .map(
        ([key, value]) => `${value} ${statusName[key]?.toLowerCase() || key}`,
      )
      .join(" · "),
    "counts",
  );
  header.append(
    counts,
    element(
      "p",
      "Positions count Unicode code points from zero; the end of a range is excluded.",
      "help",
    ),
    element(
      "p",
      "A pin is a chosen original-to-edited character correspondence.",
      "help",
    ),
  );
  const decision = element("section", undefined, "decision-bar");
  decision.setAttribute("aria-label", "Pins and export");
  const existing = element("p", undefined, "existing-pins");
  existing.append(
    element("strong", "Existing pins: "),
    element(
      "span",
      payload.binding.base_pins.length
        ? payload.binding.base_pins.map(([a, b]) => `${a} → ${b}`).join(" · ")
        : "None",
    ),
  );
  const pendingText = element("p", "No new pin selected.", "pending-pin");
  const clear = element("button", "Clear choice");
  clear.type = "button";
  clear.disabled = true;
  const download = element("button", "Export choice", "primary");
  download.type = "button";
  download.disabled = true;
  const announcement = element("p", "", "announcement");
  announcement.setAttribute("role", "status");
  announcement.setAttribute("aria-live", "polite");
  const exportPreview = element("details");
  exportPreview.append(element("summary", "Decision JSON"));
  const textarea = element("textarea");
  textarea.readOnly = true;
  textarea.setAttribute("aria-label", "Exported decision JSON");
  textarea.rows = 7;
  exportPreview.append(textarea);
  decision.append(
    existing,
    pendingText,
    clear,
    download,
    element(
      "p",
      "Native results stay unchanged until you recompute with the Signelet CLI.",
      "help",
    ),
    announcement,
    exportPreview,
  );
  const layout = element("div", undefined, "review-layout");
  const nav = element("nav", undefined, "note-navigation");
  nav.setAttribute("aria-label", "Notes");
  const searchLabel = element("label", "Find a note");
  searchLabel.htmlFor = "note-search";
  const search = element("input");
  search.id = "note-search";
  search.type = "search";
  search.placeholder = "ID or selected text";
  const list = element("div", undefined, "note-list");
  const paging = element("div", undefined, "paging");
  const previous = element("button", "Previous");
  previous.type = "button";
  const next = element("button", "Next");
  next.type = "button";
  const pageText = element("span");
  const noteStatus = element("p", "", "selected-note-status");
  noteStatus.setAttribute("role", "status");
  noteStatus.setAttribute("aria-live", "polite");
  const detailRoute = element("a", "Read selected note details", "detail-route");
  detailRoute.href = "#selected-note-detail";
  paging.append(previous, pageText, next);
  nav.append(searchLabel, search, noteStatus, detailRoute, list, paging);
  const detail = element("section", undefined, "note-detail");
  detail.id = "selected-note-detail";
  detail.setAttribute("tabindex", "-1");
  detail.setAttribute("aria-label", "Selected note");
  let nearbyPending = null;
  layout.append(nav, detail);
  const provenance = element("details", undefined, "binding-details");
  provenance.append(
    element("summary", "Input binding and model"),
    element("pre", JSON.stringify(payload.binding, null, 2)),
  );
  const fullResources = element("section", undefined, "full-resources");
  fullResources.setAttribute("aria-label", "Full resource texts");
  for (const [label, text] of [
    ["Full original text", payload.source_text],
    ["Full edited text", payload.target_text],
  ]) {
    const disclosure = element("details");
    disclosure.append(element("summary", label));
    let rendered = false;
    disclosure.addEventListener("toggle", () => {
      if (disclosure.open && !rendered) {
        disclosure.append(element("pre", text, "full-resource-text"));
        rendered = true;
      }
    });
    fullResources.append(disclosure);
  }
  app.replaceChildren(header, decision, fullResources, layout, provenance);

  function showContext(chars, start, end) {
    const parts = contextWindow(chars, start, end);
    const wrapper = element("div", undefined, "context-wrap");
    wrapper.append(
      element("p", `Context starts at ${parts.startOffset}`, "context-offset"),
    );
    const text = element("p", undefined, "text-context");
    if (parts.beforeTruncated) text.append(element("span", "…", "omission"));
    text.append(
      document.createTextNode(parts.before),
      element("mark", parts.selected),
      document.createTextNode(parts.after),
    );
    if (parts.afterTruncated) text.append(element("span", "…", "omission"));
    wrapper.append(text);
    if (parts.selectionTruncated)
      wrapper.append(
        element(
          "p",
          "Showing the first 128 selected code points; selection continues.",
          "help",
        ),
      );
    return wrapper;
  }
  function updatePending(message) {
    const summary = pending
      ? `Pending pin: ${pending.source_offset} → ${pending.target_offset} · note ${pending.note_id}`
      : "No new pin selected.";
    for (const view of [
      { text: pendingText, clear, download },
      nearbyPending,
    ].filter(Boolean)) {
      view.text.textContent = summary;
      view.clear.disabled = !pending;
      view.download.disabled = !pending;
    }
    textarea.value = pending
      ? JSON.stringify(makeDecision(payload, pending), null, 2)
      : "";
    if (message !== undefined) announcement.textContent = message;
  }
  function pendingActions() {
    const section = element("section", undefined, "candidate-decision");
    section.setAttribute("aria-label", "Pending choice and export");
    const text = element("p", "", "pending-pin");
    const clearButton = element("button", "Clear choice");
    clearButton.type = "button";
    clearButton.addEventListener("click", clearChoice);
    const exportButton = element("button", "Export choice", "primary");
    exportButton.type = "button";
    exportButton.addEventListener("click", exportChoice);
    nearbyPending = { text, clear: clearButton, download: exportButton };
    section.append(
      text,
      clearButton,
      exportButton,
      element(
        "p",
        "This exports one choice. Native results stay unchanged until CLI recomputation.",
        "help",
      ),
    );
    return section;
  }
  function drawDetail() {
    detail.replaceChildren();
    nearbyPending = null;
    const row = payload.rows.find((row) => row.id === selected);
    const summary = row
      ? `Selected note ${row.id} · ${statusName[row.status] || row.status}.`
      : "No selected note. No notes match this search.";
    if (noteStatus.textContent !== summary) noteStatus.textContent = summary;
    detailRoute.hidden = !row;
    if (!row) {
      detail.append(element("p", "No notes match this search."));
      return;
    }
    const title = element("div", undefined, "note-heading");
    title.append(
      element("h2", row.id),
      element(
        "span",
        statusName[row.status] || row.status,
        `status status-${row.status}`,
      ),
    );
    detail.append(title);
    if (row.reason)
      detail.append(element("p", row.reason.replaceAll("_", " "), "reason"));
    const data = element("div", undefined, "note-data");
    data.append(
      element("h3", "Note data"),
      element("p", row.data_preview || "No data preview."),
    );
    if (row.data_preview_truncated)
      data.append(element("p", "Data preview truncated.", "help"));
    detail.append(data);
    if (row.source) {
      detail.append(
        element("h3", `Original · [${row.source[0]}, ${row.source[1]})`),
        showContext(source, ...row.source),
      );
    } else
      detail.append(
        element(
          "p",
          "Original text range unavailable for this selector.",
          "help",
        ),
      );
    if (row.selected_text_truncated)
      detail.append(element("p", "Selected text preview truncated.", "help"));
    if (row.target)
      detail.append(
        element("h3", `Edited · [${row.target[0]}, ${row.target[1]})`),
        showContext(target, ...row.target),
      );
    if (row.status !== "review" || !row.endpoints.length) {
      detail.append(
        element(
          "p",
          row.status === "transposed"
            ? "This transfer is recorded by the native run."
            : "No eligible character choices are available in this result.",
          "help",
        ),
      );
      return;
    }
    const choices = element("fieldset", undefined, "candidate-choices");
    choices.append(
      element("legend", "Choose one equal character for the next native run"),
      element(
        "p",
        "Endpoint alternatives may not coexist on one path.",
        "help",
      ),
    );
    for (const endpoint of row.endpoints) {
      const section = element("section", undefined, "endpoint");
      section.append(
        element(
          "h3",
          `Original ${character(source[endpoint.source_offset])} at ${endpoint.source_offset}`,
        ),
      );
      if (endpoint.deletion_possible)
        section.append(
          element(
            "p",
            "Deletion is also possible for this character.",
            "warning",
          ),
        );
      if (endpoint.truncated)
        section.append(
          element(
            "p",
            `Showing ${endpoint.candidates.length} of ${endpoint.candidate_count} candidates. Other candidates are omitted.`,
            "warning",
          ),
        );
      if (!endpoint.candidates.length)
        section.append(element("p", "No target candidates recorded.", "help"));
      for (const candidate of endpoint.candidates) {
        const item = element("div", undefined, "candidate");
        const label = element("label");
        const copy = `Original ${endpoint.source_offset} → edited ${candidate.target_offset} · ${character(target[candidate.target_offset])}`;
        const kind = candidateKind(
          endpoint,
          candidate,
          source[endpoint.source_offset],
          target[candidate.target_offset],
        );
        if (kind === "eligible") {
          const input = element("input");
          input.type = "radio";
          input.name = "new-pin";
          input.checked =
            !!pending &&
            pending.note_id === row.id &&
            pending.source_offset === endpoint.source_offset &&
            pending.target_offset === candidate.target_offset;
          input.addEventListener("change", () => {
            const choice = {
              note_id: row.id,
              source_offset: endpoint.source_offset,
              target_offset: candidate.target_offset,
            };
            try {
              makeDecision(payload, choice);
              pending = choice;
              updatePending(
                "Pending pin selected. Native review status unchanged.",
              );
            } catch (error) {
              input.checked = false;
              announcement.textContent = error.message;
            }
          });
          label.append(input, element("span", copy));
          item.append(label);
        } else {
          item.append(
            element(
              "p",
              `${copy} · ${kind === "agreed" ? "Position already agreed" : "Not eligible for a new pin"}`,
              "help",
            ),
          );
        }
        item.append(
          showContext(
            target,
            candidate.target_offset,
            candidate.target_offset + 1,
          ),
        );
        section.append(item);
      }
      choices.append(section);
    }
    detail.append(pendingActions(), choices);
    updatePending();
  }
  function drawList() {
    const result = notePage(payload.rows, query, page);
    page = result.page;
    list.replaceChildren();
    const selectedMatches = result.rows.find((row) => row.id === selected);
    if (!selectedMatches) selected = result.rows[0]?.id;
    for (const row of result.rows) {
      const button = element("button", undefined, "note-button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(row.id === selected));
      button.append(
        element("strong", row.id),
        element(
          "span",
          row.selected_text || "Text unavailable",
          "note-preview",
        ),
        element(
          "span",
          statusName[row.status] || row.status,
          `status status-${row.status}`,
        ),
      );
      button.addEventListener("click", () => {
        selected = row.id;
        for (const other of list.children)
          other.setAttribute("aria-pressed", String(other === button));
        drawDetail();
      });
      list.append(button);
    }
    previous.disabled = page === 0;
    next.disabled = page === result.pages - 1;
    pageText.textContent = `${result.total} notes · ${page + 1} / ${result.pages}`;
  }
  search.addEventListener("input", () => {
    query = search.value;
    page = 0;
    drawList();
    drawDetail();
  });
  previous.addEventListener("click", () => {
    page--;
    drawList();
    drawDetail();
  });
  next.addEventListener("click", () => {
    page++;
    drawList();
    drawDetail();
  });
  function clearChoice() {
    const focusWasLocal = document.activeElement === nearbyPending?.clear;
    pending = null;
    updatePending("Pending choice cleared. Native results unchanged.");
    drawDetail();
    if (focusWasLocal) detail.focus();
  }
  function exportChoice() {
    if (!pending) return;
    const blob = new Blob(
      [JSON.stringify(makeDecision(payload, pending), null, 2) + "\n"],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
      anchor = element("a");
    anchor.href = url;
    anchor.download = "signelet-choice.json";
    app.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    announcement.textContent =
      "Decision download requested. Recompute with the native CLI to obtain a new result.";
  }
  clear.addEventListener("click", clearChoice);
  download.addEventListener("click", exportChoice);
  drawList();
  drawDetail();
  updatePending();
}
if (typeof document !== "undefined") {
  const app = document.getElementById("app"),
    data = document.getElementById("signelet-data");
  if (app && data) {
    try {
      initializeReview(JSON.parse(data.textContent), app);
    } catch (error) {
      app.replaceChildren(
        element("h1", "Review page could not load"),
        element("p", error.message),
      );
    }
  }
}
