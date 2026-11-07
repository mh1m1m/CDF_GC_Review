"""Readiness cannot infer actual external clients from a local SDK or configured token."""

from cdf_gco_crms.acceptance.connectivity import collect, permitted


def test_unconfigured_accounts_are_blocked_even_if_an_api_key_is_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_NOT_A_CREDENTIAL")
    result = collect()
    assert result["milestone"] == "BLOCKED_EXTERNAL"
    assert result["provider_credentials"]["openai_configured"] is True
    assert result["actual_chatgpt_registration"]["status"] == "BLOCKED_EXTERNAL"
    assert result["public_mcp_deployment"]["status"] == "BLOCKED_EXTERNAL"
    assert (
        result["live_case_cross_interface_and_exports"]["status"] == "BLOCKED_EXTERNAL"
    )


def test_destination_policy_is_explicit_and_does_not_allow_host_suffix_confusion():
    policy = {
        "version": 1,
        "http_network_policy": {
            "type": "restricted",
            "egress_rules": [{"host": "approved.example.test"}],
        }
    }
    assert permitted("https://approved.example.test/mcp", policy)
    assert not permitted("https://approved.example.test.attacker.test/mcp", policy)
    assert not permitted("https://approved.example.test/mcp", {})
    assert not permitted("https://approved.example.test/mcp", {**policy, "version": 99})
