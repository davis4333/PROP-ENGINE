"""Structural point-in-time tests: `raw_final_box_scores` must be
reachable from exactly one place (grading/), and grading itself refuses
non-Final rows (ADR 0007). These are cheap, no-DB source-level checks
that complement scripts/guardrails.py's static scan with an independent,
CI-enforced pytest regression (guardrails is a pre-commit hook, not a
required CI gate on its own)."""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

import cassandra.features.builders as features_builders
import cassandra.grading.service as grading_service
import cassandra.historical.challenger_negative_binomial as historical_challenger_negative_binomial
import cassandra.historical.challenger_poisson as historical_challenger_poisson
import cassandra.historical.dataset_builder as historical_dataset_builder
import cassandra.models.baseline as models_baseline
import cassandra.models.negative_binomial as models_negative_binomial
import cassandra.models.negative_binomial_regression as models_negative_binomial_regression
import cassandra.models.poisson_regression as models_poisson_regression
import cassandra.orchestration.run_slate as orchestration_run_slate
import cassandra.pit.asof as pit_asof
import cassandra.registry.service as registry_service
from cassandra.db.models.raw import RawFinalBoxScore
from cassandra.db.models.sources import Source
from cassandra.grading.service import latest_final_box_score


def _referenced_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }


def test_pit_asof_module_never_references_final_box_scores():
    """pit/asof.py has no function for raw_final_box_scores at all -- not
    just "doesn't call one," the capability structurally doesn't exist in
    this module. (Its docstring legitimately *names* raw_final_box_scores
    to explain the exclusion -- this checks actual code references, via
    the AST, not the docstring prose.)"""
    assert "RawFinalBoxScore" not in _referenced_names(pit_asof)


def test_features_module_never_references_final_box_scores():
    assert "RawFinalBoxScore" not in _referenced_names(features_builders)


def test_baseline_model_module_never_references_final_box_scores():
    assert "RawFinalBoxScore" not in _referenced_names(models_baseline)


def test_poisson_regression_model_module_never_references_final_box_scores():
    """Regression for a gap an independent leakage audit found: this
    module predates the challenger model actually going live (2026-08-08
    promotion), so this isolation suite never scanned it -- see
    registry/service.py's resolve_active_model(), which can now return
    this model instead of the baseline for a real run_slate() call."""
    assert "RawFinalBoxScore" not in _referenced_names(models_poisson_regression)


def test_registry_service_module_never_references_final_box_scores():
    """registry/service.py's resolve_active_model() is called directly
    from orchestration/run_slate.py's PROJECT stage -- genuinely part of
    the live-serving critical path now that a non-baseline model can be
    ACTIVE, so it belongs in this isolation suite alongside run_slate.py
    itself."""
    assert "RawFinalBoxScore" not in _referenced_names(registry_service)


def test_historical_dataset_builder_module_never_references_final_box_scores():
    """The training dataset builder computes actual_strikeouts labels
    from historical_pitcher_starts (a separate, already-graded subsystem
    -- CLAUDE.md non-negotiable #8), never from raw_final_box_scores."""
    assert "RawFinalBoxScore" not in _referenced_names(historical_dataset_builder)


def test_historical_challenger_poisson_module_never_references_final_box_scores():
    """The IRLS fit only ever sees rows a frozen training dataset already
    produced -- it has no business touching the live grading table at
    all."""
    assert "RawFinalBoxScore" not in _referenced_names(historical_challenger_poisson)


def test_negative_binomial_model_module_never_references_final_box_scores():
    """The negative-binomial challenger (added to fix a real tail-
    calibration gap the poisson-regression challenger was found to have)
    is a new live-servable model, same isolation requirement as every
    other model module."""
    assert "RawFinalBoxScore" not in _referenced_names(models_negative_binomial)


def test_negative_binomial_regression_model_module_never_references_final_box_scores():
    assert "RawFinalBoxScore" not in _referenced_names(models_negative_binomial_regression)


def test_historical_challenger_negative_binomial_module_never_references_final_box_scores():
    """Fits only against rows a frozen training dataset already
    produced, same as challenger_poisson.py -- no business touching the
    live grading table."""
    assert "RawFinalBoxScore" not in _referenced_names(historical_challenger_negative_binomial)


def test_grading_service_is_the_only_reader_of_final_box_scores():
    """The flip side of the above: grading/ is where RawFinalBoxScore
    usage is expected and legitimate."""
    assert "RawFinalBoxScore" in _referenced_names(grading_service)


def test_orchestration_run_slate_never_references_final_box_scores():
    """Regression for a real gap an adversarial point-in-time audit
    found: orchestration/run_slate.py sits directly upstream of/adjacent
    to features/models/decision in the same pipeline module, but this
    isolation suite never scanned it. It legitimately imports
    FinalBoxScoresMLBAdapter (a different name -- the adapter class,
    which only ever writes the raw table) and calls into
    grading.service.grade_slate() for the actual read; it must never
    reference the raw model itself directly."""
    assert "RawFinalBoxScore" not in _referenced_names(orchestration_run_slate)


def test_grading_refuses_a_final_box_score_whose_own_status_field_is_not_final(db_session):
    """Belt-and-suspenders alongside test_grading_service.py's equivalent
    test -- kept here too since it's the canonical PIT-suite statement of
    ADR 0007's "grade requires the game to be Final" rule."""
    stmt = pg_insert(Source).values(source_id="src-grading-iso", name="src-grading-iso", kind="pitcher_stats")
    stmt = stmt.on_conflict_do_nothing(index_elements=[Source.source_id])
    db_session.execute(stmt)

    now = datetime.now(UTC)
    db_session.add(
        RawFinalBoxScore(
            raw_id=uuid.uuid4(),
            source_id="src-grading-iso",
            mlb_game_pk=999201,
            player_mlb_id=8001,
            strikeouts_recorded=6,
            innings_pitched=5.0,
            pitch_count=88,
            game_status="Live",
            observed_at=now,
            ingested_at=now,
            payload={},
        )
    )
    db_session.flush()

    assert latest_final_box_score(db_session, 999201, 8001) is None
