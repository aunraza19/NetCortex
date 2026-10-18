"""Lead acceptance tests for CI wiring to Aun's canonical three-NIC router."""

from pathlib import Path
from runpy import run_path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_template_job_uses_canonical_router_and_keeps_only_safe_diagnostics():
    workflow = yaml.safe_load((ROOT / ".github/workflows/chr-templates.yml").read_text())
    steps = workflow["jobs"]["templates"]["steps"]
    runs = [step.get("run", "") for step in steps]
    setup = runs.index("python .github/scripts/chr_ci_env.py")
    start = runs.index("uv run --locked python infra/chr/chr.py start")
    harness = next(i for i, run in enumerate(runs) if "infra/chr/test_templates.py" in run)
    stop = next(step for step in steps if "infra/chr/chr.py stop" in step.get("run", ""))
    assert setup < start < harness
    assert stop["if"] == "always()"
    assert not any("chr_bootstrap.py start" in run for run in runs)
    artifacts = [
        step["with"]["path"] for step in steps if "upload-artifact" in step.get("uses", "")
    ]
    assert artifacts and all("var/chr/qemu.log" in path for path in artifacts)
    assert all(
        not any(s in path for s in ("qcow2", ".env", "*.img", "var/chr/**")) for path in artifacts
    )


def test_ci_credentials_are_masked_and_only_written_to_job_environment(
    tmp_path, monkeypatch, capsys
):
    module = run_path(str(ROOT / ".github/scripts/chr_ci_env.py"))
    monkeypatch.setattr(module["secrets"], "token_urlsafe", lambda size: "dummy-ci-password")
    target = tmp_path / "job-environment.txt"
    target.write_text("EXISTING_SETTING=preserved\n")
    module["write_ci_environment"](target)
    assert capsys.readouterr().out == "::add-mask::dummy-ci-password\n"
    values = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert values["EXISTING_SETTING"] == "preserved"
    assert values["CHR_REST_URL"] == "http://127.0.0.1:9180"
    assert values["CHR_USERNAME"] == "admin"
    assert values["CHR_PASSWORD"] == "dummy-ci-password"
    assert not (tmp_path / ".env").exists()
