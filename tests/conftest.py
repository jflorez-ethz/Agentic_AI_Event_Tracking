def anchored_verdict(action, evidence, seed=None):
    """Adapt a scripted verdict to the explicit evidence contract."""
    if action.get("action") != "verdict" or "correspondence" in action:
        return action
    seed = seed or action["ids"][0]
    lookup = evidence.get
    first = lookup(seed)
    assessments = []
    if first is not None and action["verdict"] == "supported":
        for identifier in action["ids"]:
            other = lookup(identifier)
            if identifier == seed or other is None:
                continue
            shared = sorted(set(first["frame_ids"]) & set(other["frame_ids"]))
            if shared:
                assessments.append(dict(
                    id=identifier, status="same_event", seed_quote=first["description"],
                    other_quote=other["description"], shared_frame_id=shared[0],
                ))
    return {**action, "correspondence": assessments}


def archive_descriptions(analysis):
    return {
        f.observation.id: {"description": f.observation.description, "frame_ids": [x.id for x in f.citation.frames]}
        for entry in analysis.evidence for f in entry.findings
    }
