import hashlib
import json

import httpx
import pytest
from pydantic import TypeAdapter

import visibility_live as live


FLAGS = ["--authorize-paid-calls", "--authorize-footage-transfer", "--authorize-observation-text-transfer"]


@pytest.mark.parametrize("missing", FLAGS)
def test_authorizations(tmp_path, missing):
    with pytest.raises(SystemExit):
        live.main(["--output", str(tmp_path/"run"), *(flag for flag in FLAGS if flag != missing)])
    assert not (tmp_path/"run").exists()


def reply(value):
    return httpx.Response(200, json={"modelVersion":live.MODEL, "usageMetadata":{
        "promptTokenCount":100,"candidatesTokenCount":10,"thoughtsTokenCount":15,"totalTokenCount":125},
        "candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(value)}]}}]})


def test_full_cli_pair(monkeypatch,tmp_path):
    def respond(request):
        body=json.loads(request.content)
        parts=body["contents"][0]["parts"]
        if len(parts)>1:
            assert sum("inlineData" in p for p in parts)==4
            return reply({"observations":[], "relation":None})
        c=json.loads(parts[0]["text"])
        if "visual_question" in c["relational_task"] and c["last_tool_result"] is None:
            return reply({"action":"inspect","modality":"frames","relational":True,"start_us":6030000,
                          "end_us":7030000,"sampling_step_ms":250,"reason":"Timing is unclear.",
                          "visual_question":"Which silhouettes can be distinguished?"})
        return reply({"action":"relation_verdict","verdict":"insufficient","reason":"Visibility remains uncertain."})
    real=live.GeminiAdapter.from_env
    def local(**kw):
        kw["client_args"]["transport"]=httpx.MockTransport(respond)
        return real(**kw)
    monkeypatch.setattr(live.GeminiAdapter,"from_env",local)
    monkeypatch.setenv("GEMINI_API_KEY","offline")
    dest=tmp_path/"run"
    assert live.main(["--output",str(dest),*FLAGS])==0
    key=json.loads((dest/"private-key.json").read_text())
    for arm,body in live.captures().items():
        r=json.loads((dest/arm/"result.json").read_text())
        assert r["physical_requests"][0]["request"]==body
        assert r["outcome"]["status"]=="unresolved" and not r["events"]
        folder=dest/"assessor"/key["blind_labels"][arm]
        assert len(list(folder.glob("*.png")))==len(r["evidence_ledger"])
        if arm=="specific":
            assert r["request_counts"]=={"verification":2,"perception":1}
            assert r["usage"]["perception"]["thoughtsTokenCount"]==15
            assert r["decisions"][-1]["context"]["last_tool_result"]["sampling_step_ms"]==250
            frames=r["inspections"][0]["entry"]["inspection"]["frames"]
            assert len(frames)==4 and all(f["pts"]>=0 and f["rgb24_sha256"] for f in frames)
        else:
            assert r["request_counts"]=={"verification":1} and not r["inspections"]


def test_iteration_limit_and_transport_failure(tmp_path):
    a=TypeAdapter(live.Analysis).validate_python(json.loads(live.ARCHIVE.read_text())["analysis"])
    video=live.ingest(live.ROOT/"data/raw/Meet_WalkSplit_pts.mp4")
    calls=0
    def respond(req):
        nonlocal calls
        parts=json.loads(req.content)["contents"][0]["parts"]
        if len(parts)>1:
            return reply({"observations":[],"relation":None})
        calls+=1
        start=3600000+calls*1000000
        return reply({"action":"inspect","reason":"Need separate views.","modality":"frames","relational":True,
                      "visual_question":"How visible are both figures?","start_us":start,"end_us":start+800000})
    cap=live.captures()["generic"]
    r=live.run_arm(tmp_path/"limits",cap,a,video,transport=httpx.MockTransport(respond))
    assert r["request_counts"]=={"verification":4,"perception":3}
    assert r["outcome"]["status"]=="unresolved"
    r=live.run_arm(tmp_path/"failed",cap,a,video,transport=httpx.MockTransport(lambda _:httpx.Response(503)))
    assert r["request_counts"]=={"verification":1} and r["status"]=="execution_failure"


def test_only_validated_selected_proposal_becomes_event(tmp_path):
    a=TypeAdapter(live.Analysis).validate_python(json.loads(live.ARCHIVE.read_text())["analysis"])
    video=live.ingest(live.ROOT/"data/raw/Meet_WalkSplit_pts.mp4")
    def respond(req):
        parts=json.loads(req.content)["contents"][0]["parts"]
        if len(parts)>1:
            return reply({"observations":[], "relation":{"claim":"approach","interval":{
                "start_us":6040000,"end_us":6560001},"views":[
                    {"frame_label":"F1","marks":[{"x":x,"y":60,"radius":1} for x in (30,110)]},
                    {"frame_label":"F2","marks":[{"x":x,"y":60,"radius":1} for x in (45,85)]}],
                "distinct_paths":False,"nearby_frame_label":None}})
        c=json.loads(parts[0]["text"])
        if c["last_tool_result"] is None:
            return reply({"action":"inspect","reason":"Check positions.","modality":"frames","relational":True,
                          "visual_question":"What changes in spacing?","start_us":6030000,"end_us":7030000})
        return reply({"action":"relation_verdict","verdict":"supported",
                      "relation_proposal_id":next(iter(c["relational_proposals"])),"reason":"Assess cited geometry."})
    r=live.run_arm(tmp_path/"positive",live.captures()["generic"],a,video,transport=httpx.MockTransport(respond))
    event,=r["events"]
    assert event["relation"]["continuity"]=="unresolved" and event["verdict"]=="supported"
    assert event["relation"]["citations"][0]["inspection_id"]==r["inspections"][0]["entry"]["inspection"]["id"]


@pytest.mark.parametrize("arm", ["generic", "specific"])
def test_archived_default_rate_inspection_forwards_its_question(tmp_path, arm):
    archive_dir = live.ROOT / "experiments/visibility-live-20261123T190614Z" / arm
    saved = json.loads((archive_dir / "result.json").read_text())
    decision = saved["decisions"][0]["decision"]
    question = decision["visual_question"]
    media_bodies = []

    def respond(request):
        parts = json.loads(request.content)["contents"][0]["parts"]
        if any("inlineData" in part for part in parts):
            media_bodies.append(request.content)
            return reply({"observations": [], "relation": None})
        context = json.loads(parts[0]["text"])
        if context["last_tool_result"] is None:
            return reply(decision)
        return reply({"action": "relation_verdict", "verdict": "insufficient",
                      "reason": "No supporting relation was returned."})

    archive = TypeAdapter(live.Analysis).validate_python(json.loads(live.ARCHIVE.read_text())["analysis"])
    video = live.ingest(live.ROOT / "data/raw/Meet_WalkSplit_pts.mp4")
    result = live.run_arm(tmp_path / arm, live.captures()[arm], archive, video,
                          transport=httpx.MockTransport(respond))
    inspection, = result["inspections"]
    assert inspection["options"].get("visual_question") == question
    body, = media_bodies
    instruction = f" Inspection question (an unverified lead): {question}".encode()
    assert body.count(question.encode()) == 1 and instruction in body
    # Removing just this text, and the later person_fell taxonomy addition (prompt sentence and
    # category enum entry), must reproduce the original physical media request.
    fall_additions = (
        b"Use person_fell only when cited frames show the same person upright before and lying on the "
        b"floor after; cite frames for both states. A person sitting, crouching, bending or partly hidden "
        b"is insufficient evidence. Do not infer injury, medical condition or cause. ",
        b'"person_fell", ',
    )
    assert all(body.count(text) == 1 for text in fall_additions)
    stripped = body.replace(instruction, b"")
    for text in fall_additions:
        stripped = stripped.replace(text, b"")
    old_media, = (r for r in saved["physical_requests"] if r["role"] == "perception")
    assert hashlib.sha256(stripped).hexdigest() == old_media["body_sha256"]
    assert list(inspection["entry"]["inspection"]["frames"]) == saved["inspections"][0]["entry"]["inspection"]["frames"]
    assert result["request_counts"] == saved["request_counts"]
    assert result["outcome"]["status"] == "unresolved" and not result["events"]
