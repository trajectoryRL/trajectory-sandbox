"""Tests for session._criterion_ratios — per-criterion normalised scores."""

from __future__ import annotations

import pytest

from trajrl_bench.session import _criterion_ratios


class TestCriterionRatios:
    def test_dict_of_floats(self):
        ev = {"criteria": {"a": 0.5, "b": 1.0, "c": 0.0}}
        out = _criterion_ratios(ev)
        assert out == {"a": 0.5, "b": 1.0, "c": 0.0}

    def test_list_of_score_max(self):
        ev = {"criteria": [
            {"name": "x", "score": 2, "max": 2},
            {"name": "y", "score": 1, "max": 2},
        ]}
        out = _criterion_ratios(ev)
        assert out == {"x": 1.0, "y": 0.5}

    def test_dict_of_score_max(self):
        ev = {"criteria": {
            "safety": {"score": 1.0},
            "coord":  {"score": 3, "max": 5},
        }}
        out = _criterion_ratios(ev)
        assert out == pytest.approx({"safety": 1.0, "coord": 0.6})

    def test_mixed_shapes_in_dict(self):
        # Real-world drift: values are a mix of numbers and objects.
        ev = {"criteria": {
            "completeness": 0.9,
            "safety": {"score": 1.0, "max": 1, "notes": "clean"},
            "broken": None,
        }}
        out = _criterion_ratios(ev)
        assert out == {"completeness": 0.9, "safety": 1.0}

    def test_list_drops_anonymous_entries(self):
        ev = {"criteria": [
            {"name": "named", "score": 1, "max": 1},
            {"score": 0.5, "max": 1},  # no name — drop
        ]}
        assert _criterion_ratios(ev) == {"named": 1.0}

    def test_clamped_to_unit_range(self):
        ev = {"criteria": {"over": 1.7, "under": -0.3}}
        assert _criterion_ratios(ev) == {"over": 1.0, "under": 0.0}

    def test_empty_and_missing(self):
        assert _criterion_ratios({}) == {}
        assert _criterion_ratios({"criteria": {}}) == {}
        assert _criterion_ratios({"criteria": []}) == {}

    def test_zero_max_dropped(self):
        ev = {"criteria": [
            {"name": "a", "score": 0, "max": 0},
            {"name": "b", "score": 1, "max": 1},
        ]}
        assert _criterion_ratios(ev) == {"b": 1.0}
