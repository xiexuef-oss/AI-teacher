"""联调工具（tools/e2e）里不需要浏览器的那部分：检查汇总、构建是否过期、端口、从样题里取数。

联调脚本本身要真实的浏览器、后端和 Web 构建，不在 pytest 里跑（见 tools/e2e/README.md）。
这里守的是它们依赖的数据不会悄悄走样：样题改了标题、答案、数据表，或者周报的最小样本数变了，
先在这里变红，而不是等到有人跑联调时才发现脚本对不上。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from e2e import data, servers
from e2e.checks import Checks
from e2e.flows import FLOWS, parent_weekly
from support.seeds import EXPERIMENT_KEYS, OBJECTIVE_KEYS, qid
from tutor_api.services import grading
from tutor_api.services.content_seed import load_seed
from tutor_api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestChecks:
    def test_counts_lines_and_exit_code(self):
        lines: list[str] = []
        checks = Checks(echo=lines.append)

        assert checks.check("通过的", True) is True
        assert checks.check("失败的", 0, "原因") is False

        assert checks.failed() == ["失败的"]
        assert checks.summary() == "共 2 项检查，通过 1 项，失败 1 项"
        assert checks.exit_code() == 1
        assert lines[0].startswith("  ✓ ") and "通过的" in lines[0]
        assert lines[1].startswith("  ✗ ") and "失败的" in lines[1] and "原因" in lines[1]

    def test_all_passing_exits_zero(self):
        checks = Checks(echo=lambda line: None)
        checks.check("a", 1)
        checks.check("b", "非空")
        assert checks.exit_code() == 0
        assert checks.failed() == []

    def test_a_passing_check_does_not_print_its_detail(self):
        lines: list[str] = []
        Checks(echo=lines.append).check("好的", True, "不该出现")
        assert "不该出现" not in lines[0]

    def test_a_long_detail_is_cut(self):
        lines: list[str] = []
        Checks(echo=lines.append).check("x", False, "字" * 2000)
        assert len(lines[0]) < 600

    def test_checks_can_be_merged_for_the_final_summary(self):
        first, second = Checks(echo=lambda line: None), Checks(echo=lambda line: None)
        first.check("a", True)
        second.check("b", False)
        first.extend(second)
        assert first.summary() == "共 2 项检查，通过 1 项，失败 1 项"
        assert first.failed() == ["b"]


class TestNeedsRebuild:
    @staticmethod
    def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
        built = tmp_path / "build" / "web" / "main.dart.js"
        built.parent.mkdir(parents=True)
        built.write_text("compiled")
        lib = tmp_path / "lib"
        (lib / "nested").mkdir(parents=True)
        source = lib / "nested" / "page.dart"
        source.write_text("source")
        return built, lib, source

    def test_a_missing_build_needs_a_build(self, tmp_path):
        reason = servers.needs_rebuild(tmp_path / "nope" / "main.dart.js", [tmp_path])
        assert reason and "没有" in reason

    def test_up_to_date_when_every_source_is_older(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(source, (1_000, 1_000))
        os.utime(built, (2_000, 2_000))
        assert servers.needs_rebuild(built, [lib]) is None

    def test_a_newer_source_makes_it_stale_and_names_the_file(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(built, (1_000, 1_000))
        os.utime(source, (2_000, 2_000))
        reason = servers.needs_rebuild(built, [lib])
        assert reason and "page.dart" in reason

    def test_sources_can_be_single_files(self, tmp_path):
        built, _, _ = self._tree(tmp_path)
        pubspec = tmp_path / "pubspec.yaml"
        pubspec.write_text("name: x")
        os.utime(built, (1_000, 1_000))
        os.utime(pubspec, (2_000, 2_000))
        assert servers.needs_rebuild(built, [pubspec])

    def test_a_source_that_does_not_exist_is_skipped(self, tmp_path):
        built, lib, source = self._tree(tmp_path)
        os.utime(source, (1_000, 1_000))
        os.utime(built, (2_000, 2_000))
        assert servers.needs_rebuild(built, [tmp_path / "no-such-dir", lib]) is None


def test_port_in_use_tells_a_listening_port_from_a_free_one():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert servers.port_in_use(port) is True
    assert servers.port_in_use(port) is False


class TestSeedData:
    def test_titles_come_from_the_seed(self):
        assert data.title_of("phys-tape-experiment") == "用纸带数据测小车的加速度"
        with pytest.raises(KeyError):
            data.title_of("no-such-question")

    def test_question_ids_are_the_ones_the_api_serves(self):
        assert data.question_id("math-mono-judge") == qid("math-mono-judge")

    def test_blank_cells_and_their_reference_values_line_up(self):
        cells = data.blank_cells("chem-titration-experiment")
        refs = data.reference_values("chem-titration-experiment")
        assert len(cells) == 5 and ("t1", "r1", "dv") in cells
        assert set(refs) == set(cells)
        assert refs[("t1", "r1", "dv")] == "20.05"
        assert refs[("t2", "r2", "val")] == "0.1004"

    @pytest.mark.parametrize("key", sorted(EXPERIMENT_KEYS))
    def test_every_experiment_seed_has_what_the_flows_look_at(self, key):
        question = data.question(key)
        assert question["content"]["safety"]["notes"]
        assert question["content"]["data_tables"]
        assert data.blank_cells(key)
        assert data.points_of(key)

    def test_published_counts_follow_the_seed(self):
        questions = load_seed().questions
        assert data.published_count() == len(questions)
        experiments = [q for q in questions if q["answer_mode"] == "experiment"]
        assert data.published_count("experiment") == len(experiments) == len(EXPERIMENT_KEYS)

    @pytest.mark.parametrize("key", sorted(OBJECTIVE_KEYS))
    def test_the_correct_and_the_wrong_answer_grade_as_named(self, key):
        question = data.question(key)
        for kind, expected in (("correct", True), ("wrong", False)):
            result = grading.grade(
                answer_mode=question["answer_mode"],
                content=question["content"],
                answer_key=question["answer"],
                rubric=question.get("rubric") or {},
                teaching=question.get("teaching") or {},
                answer=data.answer_for(key, kind),
            )
            assert result.is_correct is expected, (key, kind)


class TestParentWeeklyPlan:
    def test_the_plan_only_uses_questions_the_seed_has(self):
        for key, kind in parent_weekly.PLAN:
            assert data.question(key)
            if kind == "written":
                assert data.question(key)["answer_mode"] == "written"
            else:
                assert data.question(key)["answer_mode"] != "written"
                assert kind in ("correct", "wrong")

    def test_the_expected_figures_follow_from_the_plan(self):
        expected = parent_weekly.expected_weekly()
        objective = [kind for _, kind in parent_weekly.PLAN if kind != "written"]
        assert expected["attempts"] == len(parent_weekly.PLAN)
        assert expected["written"] == len(parent_weekly.PLAN) - len(objective)
        assert expected["independent_total"] == len(objective)
        assert expected["independent_correct"] == objective.count("correct")
        assert expected["rate"] == round(100 * objective.count("correct") / len(objective))

    def test_there_are_enough_samples_for_the_weekly_report_to_show_percentages(self):
        # 周报在样本不足时只给计数、不显示百分比：联调要看百分比，计划里的客观题就得够数
        assert (
            parent_weekly.expected_weekly()["independent_total"] >= Settings().progress_min_samples
        )


class TestFlowRegistry:
    def test_the_flows_are_registered_in_order(self):
        assert list(FLOWS) == ["student_experiment", "admin_experiment", "parent_weekly"]

    def test_every_flow_says_what_it_is_and_what_it_needs(self):
        for name, flow in FLOWS.items():
            assert flow.name == name
            assert flow.title
            assert flow.needs and flow.needs <= {"flutter", "admin"}

    def test_importing_the_flows_does_not_need_a_browser(self):
        # --list 和这些测试都不该因为没装 playwright 而失败
        probe = "import sys; import e2e.flows; sys.exit(1 if 'playwright' in sys.modules else 0)"
        paths = [REPO_ROOT / "tools", REPO_ROOT / "tests", REPO_ROOT / "services" / "api"]
        paths.append(REPO_ROOT / "services" / "ai_gateway")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in paths)}
        done = subprocess.run(
            [sys.executable, "-c", probe], env=env, capture_output=True, text=True, cwd=REPO_ROOT
        )
        assert done.returncode == 0, done.stderr
