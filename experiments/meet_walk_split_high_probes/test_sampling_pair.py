import json
from pathlib import Path

from google import genai
import httpx
import pytest

import sampling_pair

PLAN = Path(__file__).with_name("sampling_pair_plan")


def arm(step):
    return json.loads((PLAN / f"step-{step}/input.json").read_text())


def test_frozen_pair_is_nested_with_actual_pts_and_identical_settings():
    sparse, dense = (arm(step) for step in sampling_pair.STEPS)
    assert sparse["inspection"]["frames"] == dense["inspection"]["frames"][::2]
    assert sparse["inspection"]["requested_times_us"] == dense["inspection"]["requested_times_us"][::2]
    assert sparse["config"] == dense["config"]
    assert sparse["text_parts"][0] == dense["text_parts"][0]
    assert sparse["model"] == dense["model"] == "gemini-3.6-flash"
    video = sampling_pair.ingest(sampling_pair.SOURCE)
    for step, manifest, count in ((500, sparse, 30), (250, dense, 60)):
        assert len(manifest["pngs"]) == manifest["image_count"] == count
        assert manifest["sdk_body_bytes"] < sampling_pair.MAX_INLINE_BYTES
        frames = manifest["inspection"]["frames"]
        assert all(video.frame_pts[f["display_index"]] == f["pts"] and
                   video.time_at_pts(f["pts"]) * 1_000_000 == f["source_time_us"] for f in frames)
        assert [sampling_pair.sha((PLAN / f"step-{step}" / f["file"]).read_bytes()) for f in manifest["pngs"]] == [
            f["sha256"] for f in manifest["pngs"]
        ]


@pytest.mark.parametrize(("step", "finish"), [(500, "STOP"), (250, "MAX_TOKENS")])
def test_authorized_path_has_one_mocked_send_and_records_diagnostics(tmp_path, monkeypatch, step, finish):
    original = genai.Client
    sent = []

    def respond(request):
        sent.append(request)
        assert sampling_pair.sha(request.content) == arm(step)["sdk_body_sha256"]
        return httpx.Response(200, json={
            "candidates": [{"finishReason": finish, "content": {"parts": [{"text": '{"observations": []}'}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10, "thoughtsTokenCount": 5},
        })

    def client(**kwargs):
        options = kwargs["http_options"].client_args
        if "transport" not in options:
            options["transport"] = httpx.MockTransport(respond)
        return original(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    output = tmp_path / "result"
    args = ["run", "--prepared", str(PLAN), "--frame-step-ms", str(step), "--output", str(output)]
    with pytest.raises(SystemExit):
        sampling_pair.main(args)
    assert not output.exists() and not sent
    assert sampling_pair.main([*args, "--authorize-footage-transfer"]) == 0
    record = json.loads((output / "result.json").read_text())
    assert len(sent) == record["physical_http_requests"] == 1
    assert record["transport_attempts"][0]["http_status"] == 200
    assert record["completion"] == {"candidate_count": 1, "finish_reasons": [finish]}
    usage = dict(record["metadata"]["usage"])
    assert (usage["prompt_token_count"], usage["thoughts_token_count"], usage["candidates_token_count"]) == (20, 5, 10)
    assert record["validation"] == ("passed" if finish == "STOP" else "failed")
