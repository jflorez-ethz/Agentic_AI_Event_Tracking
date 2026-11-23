/* Scorer-compatible review export. Browser metadata is ignored by score.py. */
const Review = (() => {
  const key = (prediction) => prediction.stage + "/" + prediction.id;
  const empty = () => ({ reviewer: "", judgments: {}, exclusions: {} });
  const tasks = (prediction) => prediction.pairs.length ? prediction.pairs.map(p => p.id) : ["no-candidate"];

  function progress(cases, states) {
    let total = 0, reviewed = 0, uncertain = 0, noCandidate = 0, noCandidateTotal = 0;
    for (const item of cases) for (const prediction of item.predictions) {
      const answers = states[item.id]?.judgments[key(prediction)] ?? {};
      for (const task of tasks(prediction)) {
        const choice = answers[task]?.choice;
        if (task === "no-candidate") {
          noCandidateTotal++;
          noCandidate += Boolean(choice);
        }
        else {
          total++;
          reviewed += Boolean(choice);
        }
        uncertain += choice === "uncertain";
      }
    }
    return {total, reviewed, uncertain, noCandidate, noCandidateTotal, remaining: total - reviewed};
  }

  function exportReview(item, state) {
    const output = JSON.parse(JSON.stringify(item.draft));
    output.reviewer = state.reviewer.trim();
    const blockers = [];
    if (!output.reviewer) blockers.push("Enter a reviewer code.");
    for (const prediction of item.predictions) {
      const {id, stage} = prediction;
      const group = key(prediction);
      const judgments = state.judgments[group] ?? {};
      const exclusion = state.exclusions[group]?.trim();
      const matches = prediction.pairs.filter(p => judgments[p.id]?.choice === "match").map(p => p.id);
      if (exclusion && !matches.length) {
        delete output.event_links[stage][id];
        output.caviar_unlabelled_predictions[stage][id] = exclusion;
        continue;
      }
      const choices = tasks(prediction).map(task => judgments[task]?.choice);
      if (exclusion || choices.some(choice => !choice || choice === "uncertain")) {
        blockers.push(`${stage} ${id.slice(12, 20)}: review or resolve uncertainty.`);
        continue;
      }
      output.event_links[stage][id] = matches;
    }
    output.visual_review = {version: 1, ...state};
    return {output, blockers};
  }

  function importReview(item, file) {
    for (const hash of ["source_sha256", "artifact_sha256", "annotation_sha256"]) {
      if (item.draft[hash] !== file[hash]) throw new Error("This file belongs to a different case or artifact.");
    }
    const saved = file.visual_review;
    if (saved?.version !== 1 || typeof saved.reviewer !== "string") throw new Error("Expected a review exported from this page.");
    const state = empty();
    state.reviewer = saved.reviewer;
    for (const prediction of item.predictions) {
      const group = key(prediction);
      for (const task of tasks(prediction)) {
        const answer = saved.judgments?.[group]?.[task];
        if (!answer) continue;
        const choices = task === "no-candidate" ? ["no_match", "uncertain"] : ["match", "no_match", "uncertain"];
        if (!choices.includes(answer.choice) || typeof answer.comment !== "string") throw new Error("Invalid review judgment.");
        (state.judgments[group] ??= {})[task] = answer;
      }
      const reason = saved.exclusions?.[group];
      if (typeof reason === "string") state.exclusions[group] = reason;
    }
    return state;
  }

  return {key, empty, progress, exportReview, importReview};
})();
if (typeof module !== "undefined") module.exports = Review;
