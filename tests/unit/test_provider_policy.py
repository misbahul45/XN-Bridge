import pytest

from xnbridge.discovery import ServerProbe, ToolMeta
from xnbridge.errors import ValidationFailed


def test_authentication_hold_survives_metadata_refresh_until_operator_observation(bridge):
    probe = ServerProbe(server="gmail", transport="stdio", status="OK", tools=[ToolMeta("search_gmail_messages", "Search", {"type": "object"}, None)])
    bridge.registry.ingest([probe])
    bridge.registry.note_health("gmail", "AUTH_REQUIRED", "Owner OAuth login has not occurred")
    bridge.registry.ingest([probe])
    result = bridge.registry.resolve("email.read")
    assert result["status"] != "AVAILABLE"
    assert any(r["reason"] == "SERVER_AUTH_REQUIRED" for r in result["excluded"])
    bridge.registry.note_health("gmail", "OK", "Owner connected and verified a read outside this fixture")
    assert bridge.registry.resolve("email.read")["status"] == "AVAILABLE"


def test_health_observation_requires_detail_and_cannot_invent_states(bridge):
    for status, detail in [("OK", ""), ("APPROVED", "arbitrary")]:
        with pytest.raises(ValidationFailed):
            bridge.registry.note_health("gmail", status, detail)


def test_only_reviewed_provider_operations_are_read(bridge):
    assert bridge.classifier.classify("career-public", "search_jobs").risk == "READ"
    assert bridge.classifier.classify("gmail", "search_gmail_messages").risk == "READ"
    assert bridge.classifier.classify("gmail", "send_gmail_message").risk == "EXTERNAL_WRITE"
    assert bridge.classifier.classify("career-public", "new_unreviewed_tool").risk == "EXTERNAL_WRITE"
