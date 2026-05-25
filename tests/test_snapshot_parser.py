from app.services.snapshot_parser import NOT_COLLECTED, normalize_snapshot_payload


def test_maps_sections_explicitly():
    raw = {
        "info_no_node": '{"user":{"id":"!abcd","longName":"Nicco Pisa Berry II","shortName":"NPBe"}}',
        "nodes": '[{"num":123,"user":{"id":"!n1","longName":"Node 1","shortName":"N1"}}]',
        "config": None,
        "channels": None,
        "module_config": None,
        "export_config": "data/backups/20260525-local/NPBe_20260525-171530_export-config.txt",
    }
    normalized = normalize_snapshot_payload(
        connection_type="tcp",
        connection_target="192.168.10.8:4403",
        source={"source_node_id": "!abcd", "source_node_long_name": "Nicco Pisa Berry II", "source_node_short_name": "NPBe", "source_node_label": "NPBe - Nicco Pisa Berry II"},
        raw=raw,
    )

    assert normalized["local_device_info"]["user"]["id"] == "!abcd"
    assert len(normalized["nodes"]) == 1
    assert normalized["nodes"][0]["user"]["id"] == "!n1"
    assert normalized["export_config"].endswith("_export-config.txt")
    assert normalized["config"] == NOT_COLLECTED


def test_parse_failures_and_not_collected():
    raw = {
        "info_no_node": '{}',
        "nodes": 'not-json',
        "config": None,
        "channels": None,
        "module_config": None,
        "export_config": None,
    }
    normalized = normalize_snapshot_payload(
        connection_type="serial",
        connection_target="/dev/ttyUSB0",
        source={},
        raw=raw,
    )

    assert normalized["local_device_info"] == {}
    assert normalized["nodes"] == []
    assert "nodes: parse_failed" in normalized["parse_errors"][0]
    assert normalized["channels"] == NOT_COLLECTED
    assert normalized["module_config"] == NOT_COLLECTED
