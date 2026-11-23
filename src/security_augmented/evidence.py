"""Evidence-scope and correspondence checks for model-guided verification."""

from dataclasses import asdict

from .contracts import Interval, VideoError


class CorroborationRequired(VideoError):
    """A supported verdict needs more evidence or an event correspondence assessment."""


def tool_coverage(entries, modality, requested):
    """Summarize actual coverage and retain only findings wholly inside the request."""
    segments = []
    found = {}
    excluded = {}
    failures = 0
    for entry in entries:
        if entry.modality != modality:
            continue
        if entry.status != "success":
            failures += 1
            continue
        for span in entry.coverage:
            start = max(span.start_us, requested.start_us)
            end = min(span.end_us, requested.end_us)
            if start < end:
                segments.append((start, end))
        for finding in entry.findings:
            cite = finding.citation.interval
            identifier = finding.observation.id
            if requested.start_us <= cite.start_us and cite.end_us <= requested.end_us:
                found[identifier] = finding
            elif cite.start_us < requested.end_us and requested.start_us < cite.end_us:
                excluded[identifier] = {"id": identifier, **asdict(cite)}
    merged = []
    for start, end in sorted(segments):
        if merged and start <= merged[-1].end_us:
            last = merged[-1]
            merged[-1] = Interval(last.start_us, max(last.end_us, end))
        else:
            merged.append(Interval(start, end))
    if merged == [requested]:
        status = "covered_with_findings" if found else "covered_without_findings"
    elif merged:
        status = "partial"
    else:
        status = "failed" if failures else "missing"
    details = {
        "status": status, "requested": asdict(requested),
        "coverage": [asdict(span) for span in merged],
        "citation_spans": [{"id": i, **asdict(f.citation.interval)} for i, f in found.items()],
        "excluded_citation_spans": list(excluded.values()),
        "archived_failures": failures, "matches": len(entries),
    }
    return found, details


def assess_correspondence(seed, visible, assessments):
    """Validate the grounding of model pair judgments without inferring identities."""
    if not isinstance(assessments, list) or len(assessments) >= len(visible) + 1:
        raise VideoError("Invalid event correspondence list")
    seed_frames = {f.id for f in seed.citation.frames}
    results = {}
    for item in assessments:
        if not isinstance(item, dict) or set(item) != {
            "id", "status", "seed_quote", "other_quote", "shared_frame_id",
        }:
            raise VideoError("Invalid event correspondence assessment")
        identifier = item["id"]
        status = item["status"]
        if (not isinstance(identifier, str) or identifier == seed.observation.id
                or identifier not in visible or identifier in results
                or status not in ("same_event", "different_events", "unresolved")):
            raise VideoError("Invalid event correspondence reference or status")
        other = visible[identifier]
        for quote, observation in (
            (item["seed_quote"], seed.observation), (item["other_quote"], other.observation),
        ):
            if not isinstance(quote, str) or not quote.strip() or quote not in observation.description:
                raise VideoError("Correspondence quotes must match the cited observations")
        anchor = item["shared_frame_id"]
        other_frames = {f.id for f in other.citation.frames}
        if status == "same_event":
            if not isinstance(anchor, str) or anchor not in seed_frames & other_frames:
                raise VideoError("Same-event assessment requires a shared cited source frame")
        elif anchor is not None:
            raise VideoError("Only a same-event assessment may assert a shared frame anchor")
        results[identifier] = item
    return results
