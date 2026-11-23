const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const Review = require("./review.js");
const content = name => fs.readFileSync(path.join(__dirname, name), "utf8");
const data = JSON.parse(content("data.js").slice("window.REVIEW_DATA = ".length).trim().slice(0, -1));
const [split, together] = data;
const states = Object.fromEntries(data.map(c => [c.id, Review.empty()]));
assert.equal(Review.progress(data, states).total, 42);
assert.equal(Review.progress(data, states).reviewed, 0);
const state = states[split.id];
assert(Review.exportReview(split, state).blockers.length);
state.reviewer = "synthetic-fixture";
for (const p of split.predictions) {
  state.judgments[Review.key(p)] = Object.fromEntries((p.pairs.length ? p.pairs.map(c => c.id) : ["no-candidate"])
    .map(id => [id, {choice: "no_match", comment: ""}]));
}
const prediction = split.predictions[0];
const first = state.judgments[Review.key(prediction)][prediction.pairs[0].id];
first.choice = "uncertain";
first.comment = "Synthetic uncertainty";
const draft = Review.exportReview(split, state);
assert.equal(draft.output.event_links[prediction.stage][prediction.id], null);
assert(draft.blockers.length);
assert.deepEqual(Review.importReview(split, draft.output), state);
assert.throws(() => Review.importReview(together, draft.output), /different case/);
if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(draft.output));
first.choice = "match";
const complete = Review.exportReview(split, state);
assert.deepEqual(complete.blockers, []);
assert.deepEqual(complete.output.event_links.initial[prediction.id], [prediction.pairs[0].id]);
assert.deepEqual(Review.importReview(split, complete.output), state);
assert.deepEqual(complete.output.event_links.initial[split.predictions.find(p => !p.pairs.length).id], []);
if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(complete.output));

// Use a small DOM test double to exercise the same page script without browser dependencies.
class Element {
  constructor() {
    this.children = [];
    this.style = {};
    this.value = "";
    this.attributes = {};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  add(child) { this.append(child); }
  setAttribute(key, value) { this.attributes[key] = value; }
}
const elements = Object.fromEntries([...content("index.html").matchAll(/ id="([^"]+)"/g)].map(m => [m[1], new Element()]));
const storage = new Map();
const sandbox = vm.createContext({
  window: {REVIEW_DATA: data}, Review,
  document: {createElement: () => new Element(), getElementById: id => elements[id]},
  Option: class { constructor(text, value) { this.text = text; this.value = value; } },
  localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
});
vm.runInContext(content("page.js"), sandbox);
const tree = element => [element, ...element.children.flatMap(tree)];
assert.match(elements.progress.textContent, /0 \/ 42/);
assert(elements.export.disabled);
assert(tree(elements.evidence).some(e => e.className === "box" && e.style.left.endsWith("%")));
assert(tree(elements.evidence).some(e => e.textContent?.includes("Object 0 · walking")));
assert(tree(elements.evidence).some(e => e.textContent?.includes(prediction.citations[0].inspection_id)));
elements.case.value = together.id;
elements.case.onchange();
assert.match(elements.alignment.textContent, /62, 157, 310, 312, 566.*64/);
const uncertain = tree(elements.judgment).find(e => e.textContent === "Uncertain");
uncertain.onclick();
assert.match(elements.progress.textContent, /1 uncertain/);
assert(storage.size > 0);
