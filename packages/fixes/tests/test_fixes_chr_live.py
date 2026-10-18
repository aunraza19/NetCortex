"""Against the real CHR (infra/chr/chr.py start). Run with: uv run pytest -m live packages/fixes"""

from uuid import uuid4

import pytest
from netcortex_core import FixPlan, TemplateId
from netcortex_fixes import RouterClient, apply, dry_run, rollback

pytestmark = pytest.mark.live

QUEUE = {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 10}


@pytest.fixture(scope="module")
def chr_router():
    client = RouterClient.chr()
    yield client
    client.close()


def test_dry_run_on_chr_restores_the_config(chr_router):
    before = chr_router.export()
    result = dry_run(TemplateId.QUEUE_LIMIT, QUEUE, chr_router)
    assert result.ok, result.log
    assert chr_router.export() == before


def test_approved_fix_applies_and_rolls_back_on_chr(chr_router):
    before = chr_router.export()
    tested = dry_run(TemplateId.QUEUE_LIMIT, QUEUE, chr_router)
    plan = FixPlan(
        incident_id=uuid4(),
        template_id=TemplateId.QUEUE_LIMIT,
        params=tested.params,
        commands=tested.commands,
        rollback=tested.rollback,
        dry_run_ok=tested.ok,
        decision="approved",
    )
    try:
        apply(plan, chr_router)
        assert any("netcortex-limit-10.0.0.42" in line for line in chr_router.export())
    finally:
        rollback(plan, chr_router)
    assert chr_router.export() == before
