from app.services.snapshot_parser import normalize_snapshot_payload


def test_separates_info_no_node_from_nodes():
    raw = {
        "info_no_node": '{"user":{"id":"!abcd","longName":"Nicco Pisa Berry II","shortName":"NPBe"}}',
        "nodes": '[{"num":123,"user":{"id":"!n1","longName":"Node 1","shortName":"N1"}}]',
        "config": None,
        "channels": None,
        "module_config": None,
    }
    normalized = normalize_snapshot_payload(
        connection_type="tcp",
        connection_target="192.168.10.8:4403",
        source={"source_node_id": "!abcd", "source_node_long_name": "Nicco Pisa Berry II", "source_node_short_name": "NPBe", "source_node_label": "NPBe - Nicco Pisa Berry II"},
        raw=raw,
    )

    assert normalized["local_info"]["user"]["id"] == "!abcd"
    assert len(normalized["nodes"]) == 1
    assert normalized["nodes"][0]["user"]["id"] == "!n1"
    assert normalized["section_status"]["config"] == "Not collected"


def test_parse_failed_and_empty_states():
    raw = {
        "info_no_node": '{}',
        "nodes": 'not-json',
        "config": '{}',
        "channels": '[]',
        "module_config": '{',
    }
    normalized = normalize_snapshot_payload(
        connection_type="serial",
        connection_target="/dev/ttyUSB0",
        source={},
        raw=raw,
    )

    assert normalized["section_status"]["local_info"] == "Empty"
    assert normalized["section_status"]["nodes"] == "Parse failed"
    assert normalized["section_status"]["config"] == "Empty"
    assert normalized["section_status"]["channels"] == "Empty"
    assert normalized["section_status"]["module_config"] == "Parse failed"
