"""models/poisson_regression.py -- the numpy-free model class/predict
path. This module must be importable and usable without numpy at all
(that's the entire reason it was split out of historical/
challenger_poisson.py -- see this module's own docstring), and its
predict() math must match what the old numpy-based implementation
computed, verified against hand-computed expected values rather than
just re-deriving the same formula the code under test uses."""

from __future__ import annotations

import math
import subprocess
import sys

from cassandra.models.poisson_regression import PoissonRegressionModel, design_row


def test_design_row_shape_and_values():
    row = design_row({"expected_bf": 20.0, "recent_k_rate": 0.2, "rest_days": 5})
    assert row == [1.0, math.log1p(20.0), 0.2, 5.0, 0.0]


def test_design_row_flags_missing_rest_days():
    row = design_row({"expected_bf": 20.0, "recent_k_rate": 0.2, "rest_days": None})
    assert row[3] == 5.0  # DEFAULT_REST_DAYS
    assert row[4] == 1.0  # rest_days_missing flag


def test_predict_matches_a_hand_computed_value():
    # intercept=0.5, log1p(expected_bf) coefficient=0.0, recent_k_rate
    # coefficient=2.0, rest_days/rest_days_missing coefficients=0.0 --
    # eta = 0.5*1 + 0.0*log1p(0) + 2.0*0.3 + 0.0*5 + 0.0*0 = 1.1
    model = PoissonRegressionModel(coefficients=(0.5, 0.0, 2.0, 0.0, 0.0))
    result = model.predict({"expected_bf": 0.0, "recent_k_rate": 0.3, "rest_days": 5})
    assert math.isclose(result.mean, math.exp(1.1), rel_tol=1e-12)


def test_predict_intercept_only():
    model = PoissonRegressionModel(coefficients=(1.0, 0.0, 0.0, 0.0, 0.0))
    result = model.predict({"expected_bf": 100.0, "recent_k_rate": 0.9, "rest_days": 0})
    assert math.isclose(result.mean, math.e, rel_tol=1e-12)


def test_predict_clips_extreme_eta_to_avoid_inf():
    model = PoissonRegressionModel(coefficients=(1000.0, 0.0, 0.0, 0.0, 0.0))
    result = model.predict({"expected_bf": 20.0, "recent_k_rate": 0.2, "rest_days": 5})
    assert math.isfinite(result.mean)
    assert result.mean == math.exp(20.0)


def test_predict_cdf_is_a_valid_distribution():
    model = PoissonRegressionModel(coefficients=(0.8, 0.1, 1.0, -0.02, 0.0))
    result = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5})
    assert result.cdf(-1) == 0.0
    assert 0.0 <= result.cdf(3) <= result.cdf(10) <= 1.0


def test_models_poisson_regression_module_never_imports_numpy():
    # The entire point of this module split (see its own docstring): a
    # live pipeline deployment must be able to reconstruct and serve a
    # registered artifact's predictions without numpy installed at all.
    # Run in a fresh subprocess so no other test's prior `import numpy`
    # can make this a false pass.
    script = (
        "import sys\n"
        "assert 'numpy' not in sys.modules\n"
        "import cassandra.models.poisson_regression\n"
        "assert 'numpy' not in sys.modules, 'importing models.poisson_regression pulled in numpy'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == "OK"
