from digital_pet.diagnostics import DiagnosticsService


def test_diagnostics_redacts_credentials_and_user_paths(tmp_path):
    service = DiagnosticsService(tmp_path)
    redacted = service.redact(r'token=secret-value api_key: abc Authorization: Bearer bearer-secret {"token":"json-secret"} https://example.test/?token=query-secret E:\work\Ameath\private')

    assert "secret-value" not in redacted
    assert "abc" not in redacted
    assert "bearer-secret" not in redacted
    assert "json-secret" not in redacted
    assert "query-secret" not in redacted
    assert "Ameath" not in redacted
