import pytest

from adaptive_sampling import Request, choose, collect, evaluate


@pytest.fixture(scope="module")
def evidence():
    return collect()


@pytest.mark.parametrize("window,counts", [("overlap", (4, 8)), ("paths", (10, 19))])
def test_source_provenance(evidence, window, counts):
    sparse, dense = evidence["windows"][window]
    assert (len(sparse["frames"]), len(dense["frames"])) == counts
    assert sparse["frames"] == [frame for frame in dense["frames"] if frame in sparse["frames"]]
    assert len(dense["new_indices"]) == counts[1] - counts[0]


def test_adaptive_admission():
    request = Request(6_000_000, 8_000_000, "overlap", "Are the silhouettes separable before overlap?")
    options = dict(candidate=(6_000_000, 8_000_000), duration_us=24_960_000,
                   sufficient=False, remaining_inspections=1, remaining_requests=1, seen=set())
    assert choose(request, **options) == "inspect"
    assert choose(None, **options) == "unresolved"
    for flags, expected in [
        ({"sufficient": True}, "sufficient"),
        ({"remaining_inspections": 0}, "budget_exhausted"),
        ({"remaining_requests": 0}, "budget_exhausted"),
        ({"seen": {(6_000_000, 8_000_000, 250)}}, "already_inspected"),
        ({"candidate": (10_000_000, 11_000_000)}, "invalid_request"),
    ]:
        assert choose(request, **(options | flags)) == expected
    assert choose(Request(6_000_000, 12_000_000, "overlap", "Can both be seen?"), **options) == "invalid_request"


@pytest.mark.parametrize("arm", [0, 1])
def test_real_frames_support_local_relations_without_identity(evidence, arm):
    results = evaluate(evidence, arm)
    for claim in ("approach", "nearby", "visible_divergence"):
        assert results[claim].status == "supported"
        assert results[claim].continuity == "unresolved"
    assert results["separation"].status == "insufficient"
    assert results["joining"].status == "insufficient"
    assert any(frame["display_index"] == 175 for frame in evidence["windows"]["overlap"][arm]["frames"])
