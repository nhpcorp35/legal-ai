"""Tests OpenAI strict-schema compatibility for Q1 provisioning."""

import importlib.util
from pathlib import Path


def test_every_object_requires_every_property():
    path = Path(__file__).parent / "scripts" / "provision_case00_q1_acceptance_contract_strict.py"
    spec = importlib.util.spec_from_file_location("strict_q1_provisioner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    schema = module.semantic_payload_json_schema()

    def check(node):
        if isinstance(node, list):
            for item in node:
                check(item)
        elif isinstance(node, dict):
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node["properties"])
            for value in node.values():
                check(value)

    check(schema)
