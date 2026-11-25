"""Offline KPI table (work plan task B7) from archived runs and CAVIAR XML. Rules: rules.json (frozen first).

    .venv/bin/python experiments/kpi/kpi.py            # writes experiments/kpi/KPI.md and kpi.json
    .venv/bin/python experiments/kpi/kpi.py --heldout  # never-seen videos: KPI_heldout.md and kpi_heldout.json

No network, no provider call. Every definition is in rules.json; this file only applies it.
"""
import json
import re
from pathlib import Path
from statistics import median

from security_augmented.annotations import parse_annotations
# Read archived runs with the categories they were written with (person_fell is kept as a legacy label).
from security_augmented.workflow import EVENT_LABELS as _CURRENT, LEGACY_LABELS, READ_PRIORITY_LABELS as PRIORITY_LABELS
EVENT_LABELS = {**_CURRENT, **LEGACY_LABELS}

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RULES = json.loads((HERE / "rules.json").read_text())
CRITICAL = ("person_fell", "object_placed", "object_removed")


# ---------- reference events from the XML ----------

def video_clock(video):
    """XML frame number -> seconds on the analysed video's own clock."""
    tb = video["time_base_num"] / video["time_base_den"]
    pts, first = video["frame_pts"], video["first_display_pts"]
    return lambda n: (pts[n] - first) * tb


def xml_events(xml_path, video):
    """Critical events derived from CAVIAR labels (rules.json critical_events)."""
    frames = parse_annotations(xml_path).frames
    last = max(f.number for f in frames)
    at = video_clock(video)
    labels, objects = {}, {}
    for f in frames:
        for o in f.objects:
            fields = {tag: text.strip() for h in o.hypotheses for tag, text, _ in h.fields}
            labels.setdefault(o.id, []).append((f.number, fields))
            if "object" in fields.get("role", ""):
                objects.setdefault(o.id, []).append(f.number)
    events = []
    for oid, seq in labels.items():
        previous = None
        for n, fields in seq:
            if fields.get("context") == "drop down":
                if previous == "moving" and fields.get("situation") == "inactive":
                    events.append({"category": "person_fell", "frame": n, "t": at(n), "xml_object": oid})
                    break
                previous = fields.get("situation")
    for oid, numbers in objects.items():
        first, end = min(numbers), max(numbers)
        events.append({"category": "object_placed", "frame": first, "t": at(first), "xml_object": oid})
        if end < last - 2:
            events.append({"category": "object_removed", "frame": end + 1, "t": at(end + 1), "xml_object": oid})
    return sorted(events, key=lambda e: (e["t"], e["category"]))


# ---------- what the run produced ----------

def _s(us):
    return us / 1e6


def human_items(an):
    """Supported security events plus every review alert (rules.json human_facing_items)."""
    items = []
    for e in an["timeline"]:
        if e["verdict"] == "supported" and e["category"] in PRIORITY_LABELS:
            frames = [f for c in e["citations"] for f in c["frames"]]
            items.append({"kind": "supported", "category": e["category"], "start": _s(e["interval"]["start_us"]),
                          "end": _s(e["interval"]["end_us"]), "seed": e["observation_ids"][0], "frames": frames})
    for a in an["review"]["alerts"]:
        items.append({"kind": "needs_review:" + a["reason_code"], "category": a["category"],
                      "start": _s(a["interval"]["start_us"]), "end": _s(a["interval"]["end_us"]),
                      "seed": a["observation_id"], "frames": a["frames"]})
    return sorted(items, key=lambda i: (i["start"], i["category"]))


def observations(an, phases=None):
    """(category, possible_category, start, end) for every Perception finding, optionally by phase."""
    out = []
    for entry in an["evidence"]:
        if phases and entry["phase"] not in phases:
            continue
        for f in entry["findings"]:
            o, c = f["observation"], f["citation"]["interval"]
            out.append((o["category"], o.get("possible_category"), _s(c["start_us"]), _s(c["end_us"])))
    return out


def raw_alerts(an):
    return sum(1 for cat, possible, _, _ in observations(an, {"initial"})
               if cat in PRIORITY_LABELS or possible in PRIORITY_LABELS)


# ---------- matching ----------

def distance(item, t):
    return 0.0 if item["start"] <= t <= item["end"] else min(abs(t - item["start"]), abs(t - item["end"]))


def match(items, events, tol, mapping):
    """One-to-one greedy match by increasing distance (rules.json matching.rule)."""
    pairs = sorted(
        ((distance(i, e["t"]), i["start"], e["t"], ii, ei)
         for ii, i in enumerate(items) for ei, e in enumerate(events)
         if i["category"] in mapping[e["category"]] and distance(i, e["t"]) <= tol),
        key=lambda p: p[:3])
    used_i, used_e, matched = set(), set(), []
    for _, _, _, ii, ei in pairs:
        if ii in used_i or ei in used_e:
            continue
        used_i.add(ii); used_e.add(ei); matched.append((ii, ei))
    return matched, [i for i in range(len(items)) if i not in used_i], [e for e in range(len(events)) if e not in used_e]


def scan_end(an):
    return _s(an["coverage"]["initial_scan_end_us"])


def miss_cause(an, event, tol, mapping):
    if event["t"] > scan_end(an):
        return "not_covered"
    for cat, possible, start, end in observations(an):
        if (cat in mapping[event["category"]] or possible in mapping[event["category"]]) and \
                distance({"start": start, "end": end}, event["t"]) <= tol:
            return "dismissed"
    return "never_seen"


# ---------- time to alert ----------

def time_to_alert(run, item, t):
    """(as_run_s, live_simulated_s) or (None, None) when the trace cannot be paired with role calls."""
    an = run["analysis"]
    decisions = [(k, e["actor"]) for k, e in enumerate(an["trace"]) if e["action"] == "decision"]
    calls = run["role_calls"]
    if [a for _, a in decisions] != [c["role"] for c in calls]:
        return None, None
    verdicts = [k for k, e in enumerate(an["trace"])
                if e["actor"] == "verification" and e["action"] == "verdict" and item["seed"] in e["observation_ids"]]
    stop = verdicts[-1] if verdicts else next((k for k, a in decisions if a == "investigation"), None)
    if stop is None:
        return None, None
    agents = sum(c["elapsed_ms"] for (k, _), c in zip(decisions, calls) if k <= stop) / 1000
    initial = [e for e in an["evidence"] if e["phase"] == "initial"]
    as_run = sum(e["inference"]["elapsed_ms"] for e in initial) / 1000 + agents
    window = next((e for e in initial if _s(e["interval"]["start_us"]) <= t < _s(e["interval"]["end_us"])), None)
    if window is None:
        return as_run, None
    live = max(0.0, _s(window["interval"]["end_us"]) - t) + window["inference"]["elapsed_ms"] / 1000 + agents
    return as_run, live


# ---------- report and evidence ----------

def inspection_frames(an):
    return {f["id"]: f for e in an["evidence"] if e.get("inspection") for f in e["inspection"]["frames"]}


def citation_valid(frame, known):
    ref = known.get(frame["id"])
    return ref is not None and all(frame[k] == ref[k] for k in ("display_index", "source_time_us", "rgb24_sha256") if k in frame)


def lead_category(report):
    m = re.search(r"Lead finding: (.+?)\s*$", report, re.M)
    if not m:
        return None
    return next((cat for cat, text in EVENT_LABELS.items() if text.rstrip(".") == m.group(1).rstrip(".")), "other")


# ---------- cost ----------

def tokens(usage):
    u = dict(usage) if usage else {}
    return u.get("prompt_token_count", 0), u.get("candidates_token_count", 0) + u.get("thoughts_token_count", 0), bool(u)


def cost(run):
    an, out = run["analysis"], {}
    parts = {"perception": [(e["inference"]["model_id"], e["inference"]["usage"]) for e in an["evidence"] if e.get("inference")],
             "agents": [(c["model"], c["usage"]) for c in run["role_calls"]]}
    for tier in ("launch", "standard"):
        out[tier] = {}
        for part, rows in parts.items():
            usd = 0.0
            for model, usage in rows:
                price = RULES["prices_usd_per_million_tokens"].get(model)
                if price is None:
                    usd = None; break
                i, o, _ = tokens(usage)
                usd += (i * price[tier]["input"] + o * price[tier]["output"]) / 1e6
            out[tier][part] = usd
    out["unpriced_calls"] = sum(1 for rows in parts.values() for _, u in rows if not tokens(u)[2])
    out["tokens"] = {part: [sum(tokens(u)[k] for _, u in rows) for k in (0, 1)] for part, rows in parts.items()}
    return out


# ---------- one run ----------

def evaluate(run, events, tol, mapping, report="", unscorable_after=None):
    """unscorable_after: items starting at or after this instant lie in an unannotated tail (held-out truth only)."""
    an = run["analysis"]
    all_items = human_items(an)
    items = [i for i in all_items if unscorable_after is None or i["start"] < unscorable_after]
    unscorable = [i for i in all_items if i not in items]
    matched, false_items, missed = match(items, events, tol, mapping)
    known = inspection_frames(an)
    rows = []
    for ii, ei in matched:
        item, event = items[ii], events[ei]
        as_run, live = time_to_alert(run, item, event["t"])
        rows.append({"event": event, "item": item, "as_run_s": as_run, "live_s": live,
                     "on_time": any(abs(_s(f["source_time_us"]) - event["t"]) <= tol for f in item["frames"])})
    return {
        "events": events, "items": items,
        "found": rows,
        "missed": [{**events[e], "cause": miss_cause(an, events[e], tol, mapping)} for e in missed],
        "false_items": [items[i] for i in false_items],
        "unscorable_items": unscorable,
        "raw_alerts": raw_alerts(an),
        "cited": sum(1 for i in items if i["frames"]),
        "valid_citations": [sum(citation_valid(f, known) for i in items for f in i["frames"]),
                            sum(len(i["frames"]) for i in items)],
        "report_produced": bool(report.strip()),
        "lead": lead_category(report),
        "scanned_s": scan_end(an),
        "duration_s": an["video"]["duration_us"] / 1e6,
    }


# ---------- run selection: only the runs listed by run_all_kpi.sh ----------

def check(entry, videos=None):
    """(status, reason) of one listed run against rules.json run_selection.complete."""
    meta, path = entry["meta"], entry["path"]
    version = RULES["system_version"]
    if meta is None:
        return "failed", "pas de meta.json (run non terminé)"
    if meta.get("src_tree") != version["src_tree"]:
        return "failed", "autre version du système"
    if meta.get("exit_code") != 0:
        return "failed", f"code de sortie {meta.get('exit_code')}"
    if entry["run"] is None:
        return "failed", "pas de run/analysis.json"
    an = entry["run"]["analysis"]
    expected = (videos or RULES["videos"]).get(meta["video"], {}).get("video_sha256")
    if an["video"]["sha256"] != expected:
        alt = entry.get("sources", {}).get(meta["video"], {})
        if not (alt.get("frames_identical_to_frozen") and alt.get("sha256") == an["video"]["sha256"]):
            return "failed", "SHA-256 de la vidéo différent"
    if an.get("completion", {}).get("investigation") == "failed":
        return "failed", "Investigation en échec"
    video, cov = an["video"], an.get("coverage") or {}
    frame_s = video["last_frame_duration_pts"] * video["time_base_num"] / video["time_base_den"]
    if "review" not in an or cov.get("initial_scan") != "completed" \
            or _s(cov.get("initial_scan_end_us", 0)) < video["duration_us"] / 1e6 - frame_s - 1e-6:
        return "failed", "vidéo pas analysée en entier"
    return "complete", ""


def load_listed(listing, videos=None):
    entries = []
    for line in listing.read_text().split():
        d = ROOT / line
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else None
        run = json.loads((d / "run/analysis.json").read_text()) if (d / "run/analysis.json").exists() else None
        sources = d.parent / "sources.json"
        e = {"dir": d, "path": d / "run/analysis.json", "meta": meta, "run": run,
             "sources": json.loads(sources.read_text()) if sources.exists() else {}}
        e["status"], e["why"] = check(e, videos)
        entries.append(e)
    return entries


# ---------- table ----------

def fmt_usd(x):
    return "—" if x is None else f"{x:.3f}"


def per_month(c, tier, scanned_s):
    p = c[tier]["perception"]
    return None if p is None else p / (scanned_s / 60) * RULES["cost_per_camera_month"]["minutes_per_month"]


def label(path):
    return path.parent.parent.name


def totals(results):
    """Pooled figures used by the dev / held-out comparison."""
    rs = [r["main"] for r in results.values()]
    lives = [f["live_s"] for r in rs for f in r["found"] if f["live_s"] is not None]
    secs = sum(r["scanned_s"] for r in rs)
    human = sum(len(r["items"]) for r in rs)
    false = sum(len(r["false_items"]) for r in rs)
    unscorable = sum(len(r.get("unscorable_items", [])) for r in rs)
    return {"videos": len(rs), "events": sum(len(r["events"]) for r in rs), "found": sum(len(r["found"]) for r in rs),
            "confirmed": sum(1 for r in rs for f in r["found"] if f["item"]["kind"] == "supported"),
            "human": human, "real": human - false - unscorable, "false": false, "unscorable": unscorable,
            "false_confirmed": sum(1 for r in rs for i in r["false_items"] if i["kind"] == "supported"),
            "false_review": sum(1 for r in rs for i in r["false_items"] if i["kind"] != "supported"),
            "false_per_h": false / (secs / 3600) if secs else 0.0,
            "live_median": median(lives) if lives else None, "live_max": max(lives) if lives else None,
            "valid": [sum(r["valid_citations"][k] for r in rs) for k in (0, 1)],
            "usd_launch": sum((v["cost"]["launch"]["perception"] or 0) + (v["cost"]["launch"]["agents"] or 0) for v in results.values()),
            "perception_usd_min": sum(v["cost"]["launch"]["perception"] or 0 for v in results.values()) / (secs / 60) if secs else None,
            "minutes": secs / 60}


def main(argv=None):
    import argparse
    args = argparse.ArgumentParser()
    args.add_argument("--heldout", action="store_true", help="never-seen videos: truth from heldout_truth.json")
    heldout = args.parse_args(argv).heldout
    if heldout:
        truth = json.loads((HERE / "heldout_truth.json").read_text())
        videos, listing, stem = truth["videos"], HERE / "runs_heldout.txt", "heldout"
        script = "run_heldout.sh"
    else:
        videos, listing, stem, script = RULES["videos"], HERE / "runs.txt", "", "run_all_kpi.sh"
    if not listing.exists():
        raise SystemExit(f"{listing.relative_to(ROOT)} is missing: run experiments/kpi/{script} first")
    entries = load_listed(listing, videos)
    mapping = RULES["matching"]["strict_categories"]
    lenient = RULES["matching"]["lenient_categories"]
    tol = RULES["matching"]["tolerance_s"]
    results = {}
    for e in entries:
        if e["status"] != "complete":
            continue
        name, an = e["meta"]["video"], e["run"]["analysis"]
        if heldout:
            events = [{"category": x["category"], "t": x["t"], "frame": x["frame"], "source": x["source"]}
                      for x in videos[name]["events"]]
        else:
            events = xml_events(ROOT / "data/annotations" / videos[name]["xml"], an["video"])
        cut = videos[name].get("unscorable_after_s") if heldout else None
        report_path = e["dir"] / "run/report.md"
        report = report_path.read_text() if report_path.exists() else ""
        results[name] = {
            "run": str(e["dir"].relative_to(ROOT)),
            "wall_s": e["meta"]["end_epoch"] - e["meta"]["start_epoch"],
            "main": evaluate(e["run"], events, tol, mapping, report, cut),
            "lenient": evaluate(e["run"], events, tol, lenient, report, cut),
            "sensitivity": {t: evaluate(e["run"], events, t, mapping, report, cut)
                            for t in RULES["matching"]["sensitivity_tolerances_s"]},
            "cost": cost(e["run"]),
        }
    failures = [(e["meta"]["video"] if e["meta"] else e["dir"].name, str(e["dir"].relative_to(ROOT)), e["why"])
                for e in entries if e["status"] != "complete"]
    suffix = f"_{stem}" if stem else ""
    compare = None
    if heldout and (HERE / "kpi.json").exists():
        compare = totals(json.loads((HERE / "kpi.json").read_text())["videos"])
    (HERE / f"kpi{suffix}.json").write_text(json.dumps({"system_version": RULES["system_version"], "videos": results,
                                                       "failures": failures, "totals": totals(results) if results else None,
                                                       "dev_totals": compare}, indent=1, default=str, sort_keys=True) + "\n")
    title = "# KPI hors ligne (tâche B7) — vidéos jamais vues" if heldout else "# KPI hors ligne (tâche B7)"
    text = render(results, failures, tol, len(entries), title, compare)
    if heldout:
        text = text.replace("Vérité terrain : XML CAVIAR. Tous ces clips ont servi au développement : aucune conclusion de généralisation.",
                            "Vérité terrain : [heldout_truth.json](heldout_truth.json), figée avant les runs (XML CAVIAR, plus 2 labels manuels "
                            "à confiance faible pour LeftBag_BehindChair). Le système n’a jamais vu ces vidéos ; les nombres restent petits.")
        text = text.replace("| Événements XML |", "| Événements attendus |")
    (HERE / f"KPI{suffix}.md").write_text(text + "\n")
    print((HERE / f"KPI{suffix}.md").read_text())


def render(results, failures, tol, listed, title="# KPI hors ligne (tâche B7)", compare=None):
    L = [title, "",
         f"Version mesurée : arbre src `{RULES['system_version']['src_tree'][:7]}` (commit `{RULES['system_version']['commit'][:7]}`). "
         f"Règles figées : [rules.json](rules.json). Correspondance stricte, tolérance ±{tol:g} s. "
         f"Runs complets : {len(results)}/{listed}. Les anciens runs archivés ne sont pas lus. "
         "Vérité terrain : XML CAVIAR. Tous ces clips ont servi au développement : aucune conclusion de généralisation.", ""]
    names = sorted(results)
    # 1. Alerts and misses
    L += ["## Alertes et événements critiques", "",
          "| Vidéo | Run | Analysé | Événements XML | Retrouvés | Ratés (cause) | Alertes brutes (approx.) | Alertes à un humain | dont vraies | Fausses : confirmées / à vérifier | Fausses / h |",
          "|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
    T = dict(ev=0, found=0, missed=0, raw=0, human=0, real=0, false=0, hours=0.0, un=0, fc=0)
    for n in names:
        r = results[n]["main"]
        ev, fo, mi = len(r["events"]), len(r["found"]), len(r["missed"])
        hu, fa, un = len(r["items"]), len(r["false_items"]), len(r.get("unscorable_items", []))
        fc = sum(1 for i in r["false_items"] if i["kind"] == "supported")
        hours = r["scanned_s"] / 3600
        causes = ", ".join(f'{m["category"]} {m["t"]:.1f} s{" (label manuel)" if m.get("source") == "manual" else ""} : {m["cause"]}'
                           for m in r["missed"]) or "—"
        L.append(f'| {n} | {Path(results[n]["run"]).name} | '
                 f'{r["scanned_s"]:.1f}/{r["duration_s"]:.1f} s | {ev} | {fo}/{ev} | {mi} ({causes}) | {r["raw_alerts"]} | '
                 f'{hu} | {hu - fa - un}/{hu - un}{f" (+{un} non jugeable)" if un else ""} | {fc} / {fa - fc} | {fa / hours:.0f} |')
        for k, v in dict(ev=ev, found=fo, missed=mi, raw=r["raw_alerts"], human=hu, real=hu - fa - un, false=fa, hours=hours, un=un, fc=fc).items():
            T[k] += v
    red = f'{1 - T["human"] / T["raw"]:.0%}' if T["raw"] else "—"
    L.append(f'| **Total** | | {T["hours"] * 3600:.1f} s | **{T["ev"]}** | **{T["found"]}/{T["ev"]}** | **{T["missed"]}** | '
             f'{T["raw"]} | {T["human"]} (réduction {red}) | **{T["real"]}/{T["human"] - T["un"]}** | **{T["fc"]}** / {T["false"] - T["fc"]} | {T["false"] / T["hours"]:.0f} |')
    L += ["", "Objectif du plan : 0 événement critique raté ; au moins 70 % d’alertes en moins en gardant au moins 95 % des vrais événements. "
          "« Alertes brutes » est une approximation (observations de sécurité de la perception initiale) tant que le détecteur C1 n’existe pas. "
          "Une fausse alerte **confirmée** a reçu le verdict « supported » : elle est présentée comme un fait établi, souvent en titre du rapport. "
          "Une fausse alerte **à vérifier** (needs_review) est présentée comme incertaine et laisse la décision à l’opérateur.", ""]
    # 2. Sensitivity
    L += ["## Sensibilité à la tolérance", "", "| Tolérance | Retrouvés | Alertes vraies | Correspondance large (±2 s) |", "|---|---:|---:|---:|"]
    for t in RULES["matching"]["sensitivity_tolerances_s"][:1] + [tol] + RULES["matching"]["sensitivity_tolerances_s"][1:]:
        rs = [results[n]["main"] if t == tol else results[n]["sensitivity"][t] for n in names]
        fo = sum(len(r["found"]) for r in rs); ev = sum(len(r["events"]) for r in rs)
        hu = sum(len(r["items"]) for r in rs); re_ = hu - sum(len(r["false_items"]) for r in rs)
        extra = ""
        if t == tol:
            ls = [results[n]["lenient"] for n in names]
            extra = f'{sum(len(r["found"]) for r in ls)}/{ev} retrouvés, {sum(len(r["items"]) - len(r["false_items"]) for r in ls)}/{hu} vraies'
        L.append(f"| ±{t:g} s | {fo}/{ev} | {re_}/{hu} | {extra or '—'} |")
    L.append("")
    # 3. Time and evidence
    L += ["## Temps d’alerte et preuves", "",
          "| Vidéo | Événement (XML) | Alerte | Temps tel qu’exécuté | Temps en direct (simulé) | Image citée à ±2 s | Fait principal du rapport |",
          "|---|---|---|---:|---:|---|---|"]
    lives = []
    for n in names:
        r = results[n]["main"]
        for f in r["found"]:
            e, i = f["event"], f["item"]
            lives += [f["live_s"]] if f["live_s"] is not None else []
            s = lambda x: "inconnu" if x is None else f"{x:.0f} s"
            L.append(f'| {n} | {e["category"]} {e["t"]:.2f} s{" (label manuel)" if e.get("source") == "manual" else ""} | {i["kind"]} {i["start"]:.1f}–{i["end"]:.1f} s | '
                     f'{s(f["as_run_s"])} | {s(f["live_s"])} | {"oui" if f["on_time"] else "non"} | {r["lead"] or "—"} |')
    if lives:
        L.append(f"| **Total** | | | | médiane {median(lives):.0f} s, max {max(lives):.0f} s (cible ≤ 30 s) | | |")
    L += ["", "Bornes basses : seuls les `elapsed_ms` des appels sont enregistrés (ni heure réelle, ni décodage, ni inspections ciblées, ni pauses).", "",
          "| Vidéo | Rapport produit | Alertes avec image citée | Citations valides |", "|---|---|---:|---:|"]
    C = [0, 0, 0, 0]
    for n in names:
        r = results[n]["main"]; v, t = r["valid_citations"]
        L.append(f'| {n} | {"oui" if r["report_produced"] else "non"} | {r["cited"]}/{len(r["items"])} | {v}/{t} |')
        C = [C[0] + r["cited"], C[1] + len(r["items"]), C[2] + v, C[3] + t]
    L += [f"| **Total** | | {C[0]}/{C[1]} | {C[2]}/{C[3]} |", ""]
    # 4. Cost
    L += ["## Coût", "",
          "Tarifs `gemini-3.6-flash` en $ par million de tokens : lancement 0,75 / 3,75 (jusqu’au 31/12/2026), standard 1,50 / 7,50 (dès le 1/1/2027). "
          "Les tokens de réflexion sont facturés comme sortie, sans remise de cache.", "",
          "| Vidéo | Tokens entrée / sortie | Run lancement ($) | Run standard ($) | dont agents (lancement) | Perception / caméra / mois, lancement ($) | standard ($) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    S = dict(l=0.0, s=0.0, a=0.0, pl=0.0, ps=0.0, sec=0.0, i=0, o=0)
    for n in names:
        c, r = results[n]["cost"], results[n]["main"]
        i = sum(v[0] for v in c["tokens"].values()); o = sum(v[1] for v in c["tokens"].values())
        tl = (c["launch"]["perception"] or 0) + (c["launch"]["agents"] or 0)
        ts = (c["standard"]["perception"] or 0) + (c["standard"]["agents"] or 0)
        L.append(f'| {n} | {i:,} / {o:,} | {tl:.3f} | {ts:.3f} | {fmt_usd(c["launch"]["agents"])} | '
                 f'{per_month(c, "launch", r["scanned_s"]):,.0f} | {per_month(c, "standard", r["scanned_s"]):,.0f} |'
                 + (f' {c["unpriced_calls"]} appel(s) sans tokens' if c["unpriced_calls"] else ""))
        S = dict(l=S["l"] + tl, s=S["s"] + ts, a=S["a"] + (c["launch"]["agents"] or 0),
                 pl=S["pl"] + (c["launch"]["perception"] or 0), ps=S["ps"] + (c["standard"]["perception"] or 0),
                 sec=S["sec"] + r["scanned_s"], i=S["i"] + i, o=S["o"] + o)
    m = RULES["cost_per_camera_month"]["minutes_per_month"]
    L += [f'| **Total** | {S["i"]:,} / {S["o"]:,} | {S["l"]:.3f} | {S["s"]:.3f} | {S["a"]:.3f} | '
          f'{S["pl"] / (S["sec"] / 60) * m:,.0f} | {S["ps"] / (S["sec"] / 60) * m:,.0f} |', "",
          "Par mois : coût de la perception par minute analysée × 43 200 minutes (toute la vidéo, 30 jours). "
          "Les agents ne sont pas extrapolés au mois : leur coût suit le nombre d’événements, pas la durée. "
          "Avec la conception en deux étapes : non mesurable (pas encore de détecteur C1).", ""]
    # 5. Wall time and failures
    L += ["## Durée réelle des runs", "", "| Vidéo | Durée de la vidéo | Durée du run (horloge) |", "|---|---:|---:|"]
    for n in names:
        L.append(f'| {n} | {results[n]["main"]["duration_s"]:.1f} s | {results[n]["wall_s"]:.0f} s |')
    L += ["", "Jusqu’à 3 vidéos tournaient en parallèle : les durées incluent l’attente du fournisseur.", ""]
    L += ["## Runs en échec (hors total)", ""]
    L += ([f"- {v} (`{d}`) : {why}" for v, d, why in failures] or ["Aucun."])
    L += ["", f"Taux de réussite : {len(results)}/{listed}.", ""]
    if compare and results:
        h = totals(results)
        pct = lambda a, b: f"{a}/{b}" + (f" ({a / b:.0%})" if b else "")
        sec = lambda x: "—" if x is None else f"{x:.0f} s"
        L += ["## Comparaison avec le tableau de développement", "",
              "Même version du système, mêmes règles. Les vidéos de développement ont servi à construire le système ; celles-ci jamais. "
              "Petits nombres : une différence d’un ou deux événements ne prouve rien.", "",
              "| | Développement | Jamais vues |", "|---|---:|---:|",
              f'| Vidéos | {compare["videos"]} | {h["videos"]} |',
              f'| Événements critiques amenés à un humain | {pct(compare["found"], compare["events"])} | {pct(h["found"], h["events"])} |',
              f'| dont confirmés par l’agent | {pct(compare["confirmed"], compare["events"])} | {pct(h["confirmed"], h["events"])} |',
              f'| Alertes vraies | {pct(compare["real"], compare["human"] - compare["unscorable"])} | {pct(h["real"], h["human"] - h["unscorable"])} |',
              f'| Fausses alertes confirmées (supported) | {compare.get("false_confirmed", "—")} | {h["false_confirmed"]} |',
              f'| Fausses alertes à vérifier (needs_review) | {compare.get("false_review", "—")} | {h["false_review"]} |',
              f'| Fausses alertes par heure analysée | {compare["false_per_h"]:.0f} | {h["false_per_h"]:.0f} |',
              f'| Temps d’alerte en direct simulé, médiane / max | {sec(compare["live_median"])} / {sec(compare["live_max"])} | {sec(h["live_median"])} / {sec(h["live_max"])} |',
              f'| Citations valides | {pct(*compare["valid"])} | {pct(*h["valid"])} |',
              f'| Coût total (lancement) | {compare["usd_launch"]:.2f} $ pour {compare["minutes"]:.1f} min | {h["usd_launch"]:.2f} $ pour {h["minutes"]:.1f} min |',
              f'| Perception par minute (lancement) | {compare["perception_usd_min"]:.3f} $ | {h["perception_usd_min"]:.3f} $ |', ""]
    L += ["## Pas encore mesurable", "",
          "- Temps humain de référence (B5) : recherche manuelle dans la vidéo et rapport écrit à la main, donc ni temps jusqu’à la preuve (B6 manque aussi) ni temps de rapport gagné.",
          "- Rapports approuvés et taux de correction (B8) : `operator_label` est vide partout.",
          "- Temps d’alerte réel : aucune heure réelle enregistrée ; seulement des bornes basses.",
          "- Vraies alertes brutes et coût en deux étapes : détecteur C1 absent.",
          "- Incendie : absent de CAVIAR."]
    return "\n".join(L)


if __name__ == "__main__":
    main()
