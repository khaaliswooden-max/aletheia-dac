"""Exact-rational quantization — the float ban and the rounding directions.

Falsification target: a reduction that lets quantization INFLATE a guarantee.
Every direction must weaken the claim, and the naive float-multiply reduction
demonstrably does not.
"""
import math
import pytest

from aletheia.provenance import quantize as q


# --- the defect the exact-rational rule exists to prevent ------------------- #
@pytest.mark.parametrize("literal,naive,exact", [
    (0.99, 990000, 989999),
    (0.95, 950000, 949999),
    (0.3, 300000, 299999),
    (0.7, 700000, 699999),
])
def test_naive_float_multiply_inflates_coverage(literal, naive, exact):
    """floor(x * 1e6) rounds UP relative to the double's true value.

    The double nearest 0.99 is strictly below 0.99, so its true floor is
    989999. The naive form returns 990000 and overstates the coverage the
    producer actually asserted -- exactly the class of defect the rounding
    directions exist to prevent.
    """
    assert math.floor(literal * 1e6) == naive          # the wrong answer
    assert q.ratio_to_ppm_floor(literal) == exact      # the specified answer
    assert exact <= naive


def test_decimal_input_is_not_penalized():
    """A caller who means exactly 0.99 says so with a decimal literal."""
    assert q.ratio_to_ppm_floor("0.99") == 990000
    assert q.ratio_to_ppm_floor(0.99) == 989999


# --- rounding directions all weaken the claim ------------------------------ #
def test_coverage_floors_and_never_overstates():
    for x in [0.99, 0.92, 0.5, 0.123456789, 1.0, 0.0]:
        n = q.ratio_to_ppm_floor(x)
        assert q.exact(n) / q.PPM_SCALE <= q.exact(x)


def test_alpha_ceils_and_never_understates():
    for x in [0.01, 0.05, 0.1, 0.08, 0.0, 1.0]:
        n = q.ratio_to_ppm_ceil(x)
        assert q.exact(n) / q.PPM_SCALE >= q.exact(x)


def test_validity_window_narrows_from_both_ends():
    t = 1787471306.4185935
    iat = q.seconds_to_us_ceil(t)
    exp = q.seconds_to_us_floor(t)
    assert q.exact(iat) / q.US_PER_SECOND >= q.exact(t)   # starts no earlier
    assert q.exact(exp) / q.US_PER_SECOND <= q.exact(t)   # ends no later
    assert iat >= exp                                      # the window narrows


def test_interval_only_widens():
    lo, hi = 0.37, 0.41
    qlo = q.to_decimal_floor(lo)
    qhi = q.to_decimal_ceil(hi)
    assert q.exact(qlo[0]) * q.exact(10) ** qlo[1] <= q.exact(lo)
    assert q.exact(qhi[0]) * q.exact(10) ** qhi[1] >= q.exact(hi)


# --- range limits ---------------------------------------------------------- #
@pytest.mark.parametrize("bad", [1.5, -0.1, 2, -1])
def test_ppm_out_of_range_is_rejected(bad):
    with pytest.raises(q.QuantizationError):
        q.ratio_to_ppm_floor(bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_is_rejected(bad):
    with pytest.raises(q.QuantizationError):
        q.ratio_to_ppm_floor(bad)


def test_boundary_values_are_accepted():
    assert q.ratio_to_ppm_floor(0) == 0
    assert q.ratio_to_ppm_floor(1) == q.PPM_MAX
    assert q.ratio_to_ppm_ceil(0) == 0
    assert q.ratio_to_ppm_ceil(1) == q.PPM_MAX


def test_microsecond_range_limits():
    assert q.seconds_to_us_floor(0) == 0
    with pytest.raises(q.QuantizationError):
        q.seconds_to_us_floor(-1)
    with pytest.raises(q.QuantizationError):
        q.seconds_to_us_ceil(q.US_MAX // 1_000_000 + 1)


def test_bool_is_not_a_quantity():
    with pytest.raises(q.QuantizationError):
        q.ratio_to_ppm_floor(True)
