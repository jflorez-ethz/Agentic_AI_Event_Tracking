(() => {
  const data = window.REVIEW_DATA;
  const $ = id => document.getElementById(id);
  const node = (tag, text, className) => {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    if (className) value.className = className;
    return value;
  };
  const button = (label, fn, pressed) => {
    const b = node("button", label);
    b.type = "button";
    b.onclick = fn;
    if (pressed !== undefined) b.setAttribute("aria-pressed", String(pressed));
    return b;
  };
  const time = us => (us / 1e6).toFixed(6) + " s";
  const interval = range => `[${time(range.start_us)}, ${time(range.end_us)})`;
  const short = id => id.slice(12, 20);
  let item = data[0], prediction = item.predictions[0], selected = 0;
  const states = Object.fromEntries(data.map(c => [c.id, Review.empty()]));
  const storageKey = c => `sa-review:${c.draft.artifact_sha256}:${c.draft.annotation_sha256}`;
  for (const c of data) {
    try {
      const saved = localStorage.getItem(storageKey(c));
      if (saved) states[c.id] = Review.importReview(c, JSON.parse(saved));
    } catch {
      $("status").textContent = "Browser storage is unavailable or could not be restored. Import or save a draft.";
    }
    $("case").add(new Option(c.name, c.id));
  }

  const state = () => states[item.id];
  const group = () => Review.key(prediction);
  const currentPair = () => prediction.pairs[selected];
  const task = () => currentPair()?.id ?? "no-candidate";

  function updateProgress() {
    const p = Review.progress(data, states);
    $("progress").textContent = `${p.reviewed} / ${p.total} pairs reviewed · ${p.remaining} remaining · ${p.uncertain} uncertain · ${p.noCandidate}/${p.noCandidateTotal} no-candidate rows`;
    const {blockers} = Review.exportReview(item, state());
    $("export").disabled = blockers.length !== 0;
    $("readiness").textContent = blockers.length
      ? "Scoring export pending: " + blockers[0]
      : "This video's review is ready to export for scoring.";
  }

  function persist() {
    try {
      localStorage.setItem(storageKey(item), JSON.stringify(Review.exportReview(item, state()).output));
      $("status").textContent = "Saved in this browser. Save a draft file to retain a portable copy.";
    } catch {
      $("status").textContent = "Browser storage unavailable. Save a draft file before closing.";
    }
    updateProgress();
  }

  function frames(panel, entries, kind) {
    if (!entries.length) {
      panel.append(node("p", "No reliable frames available.", "warning"));
      return;
    }
    const figure = node("figure");
    const list = node("div", undefined, "frames");
    const controls = entries.map((entry, i) => button(String(entry.index), () => show(i), false));
    function show(i) {
      const entry = entries[i], frame = item.frames[entry.index];
      const wrap = node("div", undefined, "image-wrap");
      const img = node("img");
      img.src = frame.image;
      img.alt = `${kind} frame ${frame.display_index} at ${time(frame.source_time_us)}`;
      img.width = item.width;
      img.height = item.height;
      img.style.height = "auto";
      img.onerror = () => wrap.replaceChildren(node("p", "Frame image is missing. Rebuild the local assets.", "warning"));
      wrap.append(img);
      if (entry.box) {
        const {xc, yc, width, height} = entry.box;
        const left = Math.max(0, xc - width / 2), top = Math.max(0, yc - height / 2);
        const box = node("span", undefined, "box");
        box.style.left = `${100 * left / item.width}%`;
        box.style.top = `${100 * top / item.height}%`;
        box.style.width = `${100 * (Math.min(item.width, xc + width / 2) - left) / item.width}%`;
        box.style.height = `${100 * (Math.min(item.height, yc + height / 2) - top) / item.height}%`;
        wrap.append(box);
      }
      figure.replaceChildren(wrap, node("figcaption",
        `Frame ${frame.display_index} · PTS ${frame.pts} · ${time(frame.source_time_us)}` +
        (entry.annotation_frame === undefined ? "" : ` · XML frame ${entry.annotation_frame}`)));
      controls.forEach((b, j) => b.setAttribute("aria-pressed", String(i === j)));
    }
    list.append(...controls);
    panel.append(figure, node("p", "Select a frame to inspect the sequence.", "meta"), list);
    show(0);
  }

  function renderCandidates() {
    const nav = $("candidates");
    nav.replaceChildren(...prediction.pairs.map((pair, i) => {
      const choice = state().judgments[group()]?.[pair.id]?.choice;
      return button(`Object ${pair.object_id} · IoU ${pair.iou.toFixed(2)}${choice ? " · " + choice.replace("_", " ") : ""}`, () => {
        selected = i;
        render();
      }, i === selected);
    }));
  }

  function renderJudgment() {
    const pair = currentPair();
    const answer = state().judgments[group()]?.[task()];
    const panel = $("judgment"), choices = node("div", undefined, "choices");
    const options = pair ? [["Match", "match"], ["No match", "no_match"], ["Uncertain", "uncertain"]]
                         : [["Reviewed — no match at threshold", "no_match"], ["Uncertain", "uncertain"]];
    for (const [label, choice] of options) choices.append(button(label, () => {
      (state().judgments[group()] ??= {})[task()] = {choice, comment: comment.value};
      persist();
      renderCandidates();
      renderJudgment();
    }, answer?.choice === choice));
    const note = node("label", "Reviewer comment");
    const comment = node("textarea");
    comment.rows = 2;
    comment.value = answer?.comment ?? "";
    comment.disabled = !answer;
    comment.oninput = () => {
      state().judgments[group()][task()].comment = comment.value;
      persist();
    };
    note.append(comment);
    const scope = node("label", "Unlabelled-region exclusion for this prediction (optional reason)");
    const exclusion = node("input");
    exclusion.value = state().exclusions[group()] ?? "";
    exclusion.oninput = () => {
      state().exclusions[group()] = exclusion.value;
      persist();
    };
    scope.append(exclusion);
    panel.replaceChildren(node("h2", pair ? `Adjudicate object ${pair.object_id}` : "Review prediction without a candidate"),
      choices, note, scope);
  }

  function render() {
    const alignment = $("alignment");
    const flags = item.alignment.flagged_indices, missing = item.alignment.missing_original_pts;
    alignment.hidden = !flags.length && !missing.length;
    alignment.textContent = `Alignment flags — near-neighbor ambiguity: ${flags.join(", ") || "none"}; missing original MPEG PTS: ${missing.join(", ") || "none"}.`;
    renderCandidates();

    const left = node("section", undefined, "panel");
    left.append(node("h2", "Gemini prediction"),
      node("div", `${prediction.stage === "initial" ? "Initial observation" : "Archived supported verdict"} · ${interval(prediction.interval)}`, "meta"),
      node("p", prediction.description, "description"));
    frames(left, prediction.frames.map(index => ({index})), "Cited source");
    const cites = node("details");
    cites.append(node("summary", "Source citations"));
    for (const citation of prediction.citations) cites.append(node("p",
      `${citation.inspection_id} · ${citation.modality} · ${interval(citation.interval)} · ${citation.frames.map(f => f.display_index).join(", ")}`));
    left.append(cites);

    const right = node("section", undefined, "panel");
    right.append(node("h2", "CAVIAR reference"));
    const pair = currentPair();
    if (pair) {
      right.append(node("div", `Object ${pair.object_id} · ${pair.label} · IoU ${pair.iou.toFixed(3)}`, "meta"),
        node("p", `${interval(pair.interval)} · ${pair.id}`, "description"));
      frames(right, pair.frames, `CAVIAR object ${pair.object_id}`);
      for (const warning of pair.warnings) right.append(node("p", warning, "warning"));
    } else right.append(node("p", "No reference meets the temporal threshold. Review the cited prediction before deciding.", "warning"));
    $("evidence").replaceChildren(left, right);
    renderJudgment();
    updateProgress();
  }

  function selectCase(next) {
    item = next;
    $("case").value = item.id;
    $("reviewer").value = state().reviewer;
    $("prediction").replaceChildren(...item.predictions.map((p, index) => new Option(
      `${p.stage === "initial" ? "Initial" : "Verified"} · ${time(p.interval.start_us)} · ${short(p.id)}`, index
    )));
    prediction = item.predictions[0];
    selected = 0;
    render();
  }

  $("case").onchange = () => selectCase(data.find(c => c.id === $("case").value));
  $("prediction").onchange = () => {
    prediction = item.predictions[Number($("prediction").value)];
    selected = 0;
    render();
  };
  $("reviewer").oninput = () => {
    state().reviewer = $("reviewer").value;
    persist();
  };

  function download(draft) {
    const {output, blockers} = Review.exportReview(item, state());
    if (!draft && blockers.length) return;
    const reviewer = state().reviewer.replace(/[^a-z0-9_-]+/gi, "-") || "reviewer";
    const url = URL.createObjectURL(new Blob([JSON.stringify(output, null, 2) + "\n"], {type: "application/json"}));
    const link = node("a");
    link.href = url;
    link.download = `${item.id}.${reviewer}.${draft ? "draft" : "reviewed"}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("status").textContent = draft ? "Draft exported. Import it to resume." : "Score-ready review exported.";
  }

  $("draft").onclick = () => download(true);
  $("export").onclick = () => download(false);
  $("import").onclick = () => $("file").click();
  $("file").onchange = async () => {
    const file = $("file").files[0];
    if (!file) return;
    try {
      const model = JSON.parse(await file.text());
      const target = data.find(c => c.draft.artifact_sha256 === model.artifact_sha256);
      if (!target) throw new Error("Unknown review artifact.");
      const next = Review.importReview(target, model);
      const previous = states[target.id];
      const hasDraft = previous.reviewer || Object.keys(previous.judgments).length || Object.keys(previous.exclusions).length;
      if (hasDraft && !confirm("Replace this case's browser draft with the imported review?")) return;
      states[target.id] = next;
      selectCase(target);
      persist();
      $("status").textContent = "Review imported. You can continue editing.";
    } catch (error) {
      $("status").textContent = error.message;
    } finally {
      $("file").value = "";
    }
  };
  selectCase(item);
})();
