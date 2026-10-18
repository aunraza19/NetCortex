import sys

from netcortex_core import ModuleUnavailable

from netcortex_detector import runtime


def test_worker_cli_reports_only_exception_type(monkeypatch, caplog, capsys):
    secret = "synthetic-secret-value"
    provider_url = "https://provider.invalid/path"

    def fail_setup(_artifact):
        raise ModuleUnavailable(f"failed at {provider_url} with token {secret}")

    monkeypatch.setattr(runtime, "configure_detector", fail_setup)
    monkeypatch.setattr(sys, "argv", ["netcortex-detector-worker", "--artifact", "training.json"])

    assert runtime.main() == 1

    output = caplog.text + capsys.readouterr().err
    assert "ModuleUnavailable" in output
    assert secret not in output
    assert provider_url not in output
