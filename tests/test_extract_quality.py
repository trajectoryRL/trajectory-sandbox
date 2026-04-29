"""Tests for session._extract_quality (v3.4.0 weighted-criteria semantics).

The function ignores the judge's emitted `quality` field and computes a
deterministic score from named codebase_fix criteria
(tests_pass / code_quality / change_minimality + learning trio). Generic-named
criteria are dropped. tests_pass can be overridden by objective test_results.
"""

from __future__ import annotations

import pytest

from trajrl_bench.session import _extract_quality


class TestExtractQuality:
    def test_empty_evaluation_returns_zero(self):
        assert _extract_quality({}) == 0.0
        assert _extract_quality(None) == 0.0
        assert _extract_quality({"criteria": {}}) == 0.0
        assert _extract_quality({"criteria": []}) == 0.0

    def test_unknown_criteria_dropped(self):
        ev = {"criteria": {"a": 1.0, "b": 0.5}}
        assert _extract_quality(ev) == 0.0

    def test_explicit_quality_field_ignored(self):
        ev = {"quality": 0.95, "criteria": {"tests_pass": 0.0}}
        assert _extract_quality(ev) == 0.0

    def test_only_tests_pass_renormalises_to_full_score(self):
        ev = {"criteria": {"tests_pass": 1.0}}
        assert _extract_quality(ev) == pytest.approx(1.0)

    def test_partial_base_renormalises(self):
        # tests_pass=1.0 (w=0.5), code_quality=0.0 (w=0.15) → 0.5 / 0.65.
        ev = {"criteria": {"tests_pass": 1.0, "code_quality": 0.0}}
        assert _extract_quality(ev) == pytest.approx(0.5 / 0.65)

    def test_full_base_set_caps_at_one(self):
        ev = {"criteria": {"tests_pass": 1.0, "code_quality": 1.0, "change_minimality": 1.0}}
        assert _extract_quality(ev) == pytest.approx(1.0)

    def test_single_learning_criterion_counts(self):
        # tests_pass=1.0 (w=0.5) + no_repeat_mistake=1.0 (w=0.25) → 0.75/0.75 = 1.0.
        ev = {"criteria": {"tests_pass": 1.0, "no_repeat_mistake": 1.0}}
        assert _extract_quality(ev) == pytest.approx(1.0)

    def test_learning_criteria_averaged(self):
        # Two learning criteria → mean. tests_pass=0 (w=0.5),
        # [no_repeat_mistake=1.0, fix_transfer=0.0] mean=0.5 (w=0.25).
        # quality = 0 + 0.25*0.5 = 0.125; total weight = 0.75; result = 0.125/0.75.
        ev = {"criteria": {"tests_pass": 0.0, "no_repeat_mistake": 1.0, "fix_transfer": 0.0}}
        assert _extract_quality(ev) == pytest.approx(0.125 / 0.75)

    def test_score_max_dict_shape(self):
        # JUDGE.md sometimes emits {score, max} per criterion.
        ev = {"criteria": {
            "tests_pass":   {"score": 4,   "max": 5},     # 0.8
            "code_quality": {"score": 0.6, "max": 1.0},   # 0.6
        }}
        # 0.5*0.8 + 0.15*0.6 = 0.49; total = 0.65.
        assert _extract_quality(ev) == pytest.approx(0.49 / 0.65)

    def test_list_of_named_criteria_shape(self):
        # Sonnet drift: list of {name, score, max}. Unknown names dropped.
        ev = {"criteria": [
            {"name": "tests_pass",   "score": 1.0, "max": 1.0},
            {"name": "code_quality", "score": 0.5, "max": 1.0},
            {"name": "irrelevant",   "score": 1.0, "max": 1.0},
        ]}
        # 0.5*1.0 + 0.15*0.5 = 0.575; total = 0.65.
        assert _extract_quality(ev) == pytest.approx(0.575 / 0.65)

    def test_objective_test_results_override_judge_tests_pass(self):
        # Judge said 0; bench's pytest result is the source of truth.
        ev = {"criteria": {"tests_pass": 0.0}}
        assert _extract_quality(ev, test_results={"passed": 4, "total": 5}) == pytest.approx(0.8)

    def test_objective_test_results_inject_when_absent(self):
        # Even if the judge never wrote tests_pass, bench injects it.
        ev = {"criteria": {"code_quality": 1.0}}
        # tests_pass=0.8 (w=0.5) + code_quality=1.0 (w=0.15)
        # quality = 0.4 + 0.15 = 0.55; total = 0.65.
        result = _extract_quality(ev, test_results={"passed": 4, "total": 5})
        assert result == pytest.approx(0.55 / 0.65)

    def test_clamped_to_unit_interval(self):
        ev = {"criteria": {"tests_pass": 5.0}}
        assert _extract_quality(ev) == pytest.approx(1.0)

    def test_malformed_values_dropped(self):
        ev = {"criteria": {
            "tests_pass":   1.0,
            "code_quality": "not a number",
            "change_minimality": None,
            "no_repeat_mistake": {"notes": "no score"},
        }}
        # Only tests_pass=1.0 counts. 0.5*1.0/0.5 = 1.0.
        assert _extract_quality(ev) == pytest.approx(1.0)

    def test_max_zero_dropped(self):
        ev = {"criteria": {
            "tests_pass":   {"score": 0, "max": 0},  # divide-by-zero guard → dropped
            "code_quality": {"score": 1, "max": 1},
        }}
        # Only code_quality=1.0 (w=0.15) counts → 0.15/0.15 = 1.0.
        assert _extract_quality(ev) == pytest.approx(1.0)
