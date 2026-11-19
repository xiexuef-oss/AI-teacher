"""A separate, self-authored adapter process exits without gateway cleanup."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import select

from ai_gateway.budget import estimate_request_cost_micros
from ai_gateway.config import Pricing
from support import REPO_ROOT
from support.gateway_fakes import external_provider, make_request
from tutor_api.models import ModelBudgetUsage


@pytest.mark.parametrize("attempts", [1, 2])
def test_actual_worker_exit_keeps_committed_dual_scope_cost(app, client, clock, attempts):
    request = make_request(student_pseudonym="stu_self_authored_crash")
    estimate = estimate_request_cost_micros(
        Pricing.model_validate(external_provider()["pricing"]), request
    )
    script = f"""
import os
from datetime import datetime
from ai_gateway import GatewayConfig,ProviderError,build_gateway
from tutor_api.db import make_engine,create_session_factory
from tutor_api.gateway_io import DbBudgetStore
from support.gateway_fakes import FULL_ENV,EVENT_SCHEMA_PATH,VISUAL_REGISTRY_PATH,config_dict,external_provider,make_request
now=datetime.fromisoformat({clock.now().isoformat()!r})
engine=make_engine({app.state.settings.database_url!r})
store=DbBudgetStore(create_session_factory(engine),lambda:now)
class ExitWorker:
    calls=0
    def invoke(self,**kwargs):
        self.calls+=1
        if self.calls<{attempts}:
            raise ProviderError('timeout')
        os._exit(23)
gateway=build_gateway(GatewayConfig.model_validate(config_dict({{'x':external_provider()}},['x'])),
    env=FULL_ENV,environment='local',allow_external_calls=True,
    event_schema_path=EVENT_SCHEMA_PATH,visual_registry_path=VISUAL_REGISTRY_PATH,
    adapter_overrides={{'x':ExitWorker()}},budget_store=store,now=lambda:now,sleep=lambda _:None)
gateway.invoke(make_request(student_pseudonym='stu_self_authored_crash'))
raise AssertionError('adapter exit was not reached')
"""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.update(
        PYTHONUTF8="1",
        PYTHONPATH=os.pathsep.join(
            str(REPO_ROOT / p) for p in ("services/api", "services/ai_gateway", "tests")
        ),
    )
    result = subprocess.run(
        [sys.executable, "-"], input=script.encode(), env=env, capture_output=True, timeout=20
    )
    assert result.returncode == 23, "self-authored crash adapter must have been reached"
    # A fresh DB session after actual process death, not an in-process exception mock.
    with app.state.session_factory() as db:
        rows = list(
            db.scalars(
                select(ModelBudgetUsage).where(ModelBudgetUsage.usage_date == clock.now().date())
            )
        )
        assert len(rows) == 2
        assert {row.scope for row in rows} == {"platform", "student"}
        assert all(row.request_count == 1 for row in rows)
        assert all(row.estimated_cost_micros == attempts * estimate for row in rows)
