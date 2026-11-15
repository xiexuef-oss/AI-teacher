"""联调流程的登记处：入口 run.py 按这里的顺序跑。每条流程自己带数据来源，互不依赖。"""

from __future__ import annotations

from e2e.flowbase import Flow
from e2e.flows import admin_experiment, parent_weekly, student_experiment, student_proof

FLOWS: dict[str, Flow] = {
    flow.name: flow
    for flow in (
        student_experiment.FLOW,
        student_proof.FLOW,
        admin_experiment.FLOW,
        parent_weekly.FLOW,
    )
}

__all__ = ["FLOWS", "admin_experiment", "parent_weekly", "student_experiment", "student_proof"]
