"""models/negative_binomial_regression.py -- the numpy-free model class/
predict path. Mirrors test_poisson_regression.py's coverage since this
model deliberately reuses the exact same mean-regression math (design_row,
coefficients) -- only the returned distribution differs."""

from __future__ import annotations

import math
import subprocess
import sys

from cassandra.models.negative_binomial import NegativeBinomialStrikeoutDistribution
from cassandra.models.negative_binomial_regression import NegativeBinomialRegressionModel


def test_predict_matches_a_hand_computed_mean():
    # Same design_row/coefficients math as PoissonRegressionModel's own
    # hand-computed test -- eta = 0.5*1 + 0.0*log1p(0) + 2.0*0.3 = 1.1.
    model = NegativeBinomialRegressionModel(coefficients=(0.5, 0.0, 2.0, 0.0, 0.0), dispersion=0.1)
    result = model.predict({"expected_bf": 0.0, "recent_k_rate": 0.3, "rest_days": 5})
    assert math.isclose(result.mean, math.exp(1.1), rel_tol=1e-12)


def test_predict_returns_a_negative_binomial_distribution_with_the_fitted_dispersion():
    model = NegativeBinomialRegressionModel(coefficients=(1.0, 0.0, 0.0, 0.0, 0.0), dispersion=0.25)
    result = model.predict({"expected_bf": 100.0, "recent_k_rate": 0.9, "rest_days": 0})
    assert isinstance(result, NegativeBinomialStrikeoutDistribution)
    assert result.dispersion == 0.25
    assert math.isclose(result.mean, math.e, rel_tol=1e-12)


def test_predict_clips_extreme_eta_to_avoid_inf():
    model = NegativeBinomialRegressionModel(coefficients=(1000.0, 0.0, 0.0, 0.0, 0.0), dispersion=0.1)
    result = model.predict({"expected_bf": 20.0, "recent_k_rate": 0.2, "rest_days": 5})
    assert math.isfinite(result.mean)
    assert result.mean == math.exp(20.0)


def test_predict_variance_exceeds_the_poisson_regression_variance_for_the_same_mean():
    # The whole point of this model family: same mean as
    # PoissonRegressionModel would produce for identical coefficients,
    # but strictly more variance (the diagnosed real-data overdispersion
    # fix).
    coefficients = (0.8, 0.1, 1.0, -0.02, 0.0)
    features = {"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5}
    nb_model = NegativeBinomialRegressionModel(coefficients=coefficients, dispersion=0.1)
    nb_result = nb_model.predict(features)
    assert nb_result.sd**2 > nb_result.mean


def test_predict_cdf_is_a_valid_distribution():
    model = NegativeBinomialRegressionModel(coefficients=(0.8, 0.1, 1.0, -0.02, 0.0), dispersion=0.1)
    result = model.predict({"expected_bf": 22.0, "recent_k_rate": 0.22, "rest_days": 5})
    assert result.cdf(-1) == 0.0
    assert 0.0 <= result.cdf(3) <= result.cdf(10) <= 1.0


def test_predict_raises_loudly_on_nan_input_rather_than_silently_producing_nan():
    model = NegativeBinomialRegressionModel(coefficients=(0.8, 0.1, 1.0, -0.02, 0.0), dispersion=0.1)
    try:
        model.predict({"expected_bf": 22.0, "recent_k_rate": float("nan"), "rest_days": 5})
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_models_negative_binomial_regression_module_never_imports_numpy():
    # Same reasoning as poisson_regression.py's equivalent test: a live
    # pipeline deployment must be able to reconstruct and serve a
    # registered artifact's predictions without numpy installed at all.
    script = (
        "import sys\n"
        "assert 'numpy' not in sys.modules\n"
        "import cassandra.models.negative_binomial_regression\n"
        "assert 'numpy' not in sys.modules, "
        "'importing models.negative_binomial_regression pulled in numpy'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert result.stdout.strip() == "OK"
