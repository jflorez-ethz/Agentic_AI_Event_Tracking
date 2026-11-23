import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import evaluate as runner


def test_packets_are_blind_and_change_only_intended_input():
    packets = dict((case, (parts, refs)) for case, parts, refs in runner.packets())
    assert len(packets) == 3
    a, b, c = (packets[i][0] for i in ("K7", "M2", "Q4"))
    assert [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y] == [4]
    assert [i for i, (x, y) in enumerate(zip(a, c, strict=True)) if x != y] == [0]
    for parts, refs in packets.values():
        assert set(refs) == {"F1", "F2", "F3"}
        assert len([x for x in parts if "inline_data" in x]) == 3
        assert [x["text"] for x in parts if "text" in x][1:] == ["F1", "F2", "F3"]


@pytest.mark.parametrize(("decision", "ids", "finish", "expected"), [
    ("same_person", ["F1", "F3"], "STOP", "schema_and_references_valid"),
    ("different_person", ["F1", "F3"], "STOP", "schema_and_references_valid"),
    ("indeterminate", ["F2"], "STOP", "schema_and_references_valid"),
    ("same_person", ["F2"], "STOP", "invalid_output"),
    ("different_person", ["F1", "F4"], "STOP", "invalid_output"),
    ("indeterminate", ["F1"], "MAX_TOKENS", "invalid_output"),
])
def test_decision_and_reference_validation(decision, ids, finish, expected):
    client = Mock()
    client.models.generate_content.return_value = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=finish)],
        text=json.dumps({"decision": decision, "frame_ids": ids, "reason": "Offline fixture"}),
        usage_metadata=SimpleNamespace(total_token_count=17),
    )
    row = runner.evaluate(client, [], dict.fromkeys(("F1", "F2", "F3")))
    assert row["status"] == expected
    assert row["usage"]["total_token_count"] == 17
    assert "raw_response" in row and "elapsed_ms" in row
    client.models.generate_content.assert_called_once_with(model=runner.MODEL, contents=[], config=runner.CONFIG)


def test_live_requires_authorization_before_client(tmp_path, monkeypatch):
    factory = Mock(side_effect=AssertionError("network client should not be created"))
    monkeypatch.setattr(runner.GeminiAdapter, "from_env", factory)
    with pytest.raises(SystemExit):
        runner.main(["--live", "--output", str(tmp_path / "blocked")])
    assert runner.main(["--output", str(tmp_path / "plan")]) == 0
    factory.assert_not_called()


def test_matrix_controls_and_exact_markers(tmp_path):
    variants = {key: (parts, refs, config, marked)
                for key, parts, refs, config, marked in runner.matrix_inputs(tmp_path)}
    assert len(variants) == 8
    common = {k: v for k, v in variants["K7-A"][2].items() if k != "thinking_config"}
    assert common["max_output_tokens"] == 4096
    manifest = json.loads((runner.ROOT / "manifest.json").read_text())
    for case in ("K7", "Q4"):
        original = variants[f"{case}-A"][0]
        for arm, marked, level in runner.MATRIX:
            parts, refs, config, actual_marked = variants[f"{case}-{arm}"]
            assert marked == actual_marked
            assert config["thinking_config"]["thinking_level"] == level
            assert {k: v for k, v in config.items() if k != "thinking_config"} == common
            assert list(refs) == ["F1", "F2", "F3"]
            assert [v["index"] for v in refs.values()] == [250, 300, 325]
            assert [i for i, (a, b) in enumerate(zip(parts, original, strict=True)) if a != b] == ([2, 6] if marked else [])
        for fid, field in (("F1", "start_region_xy"), ("F3", "end_region_xy")):
            meta = variants[f"{case}-C"][1][fid]
            x, y = manifest["cases"][case][field]
            assert meta["marker_center_xy"] == [x, y]

            def decode(path):
                return runner._run("ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                                   "-pix_fmt", "rgb24", "-threads", "1", "pipe:1").stdout

            source = decode(runner.ROOT / "packets" / case / meta["file"])
            target = decode(tmp_path / "marked" / case / f"{fid}.png")
            assert len(source) == len(target) == 384 * 288 * 3
            for offset in range(0, len(source), 3):
                j, i = divmod(offset // 3, 384)
                expected = bytes((255, 0, 0)) if 49 <= (i-x)**2 + (j-y)**2 <= 64 else source[offset:offset+3]
                assert target[offset:offset+3] == expected
    assert variants["K7-C"][0][2] == variants["Q4-C"][0][2]
    assert variants["K7-C"][0][4] == variants["Q4-C"][0][4]
    assert variants["K7-C"][0][6] != variants["Q4-C"][0][6]


def test_matrix_call_ceiling_and_usage(tmp_path, monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.models.generate_content.return_value = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="STOP")], model_version="fixture-version",
        text='{"decision":"same_person","frame_ids":["F1","F3"],"reason":"Offline fixture."}',
        usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=2, thoughts_token_count=3),
    )
    factory = Mock(return_value=SimpleNamespace(client=client))
    monkeypatch.setattr(runner.GeminiAdapter, "from_env", factory)
    output = tmp_path / "matrix"
    assert runner.main(["--matrix", "--live", "--authorize-image-transfer", "--output", str(output)]) == 0
    assert client.models.generate_content.call_count == 8
    factory.assert_called_once_with(authorized=True, model=runner.MODEL, client_args={"follow_redirects": False})
    for case in ("K7", "Q4"):
        for arm, marked, level in runner.MATRIX:
            row = json.loads((output / f"{case}-{arm}.json").read_text())
            assert (row["marked"], row["thinking_level"], row["max_output_tokens"]) == (marked, level, 4096)
            assert row["model_version"] == "fixture-version"
            assert row["usage"] == {"prompt_token_count": 1, "candidates_token_count": 2, "thoughts_token_count": 3}
