"""
quantize.py — exact-rational reduction of real quantities to signed integers.

No floating-point value ever reaches a signed payload (docs/WIRE_FORMAT.md §4).
This module is the single specified reduction from a real-valued input to the
integer that gets signed. Stdlib only.

The reduction is *exact-rational*: a Python ``float`` is interpreted as the
exact binary value the IEEE-754 double actually holds, not as the decimal
literal the author typed. That distinction is load-bearing and visible:

    >>> ratio_to_ppm_floor(0.99)      # the double is strictly below 0.99
    989999
    >>> ratio_to_ppm_floor("0.99")    # an exact decimal input
    990000

Reporting 989999 for the double is the truthful reading — the producer did not
assert 0.99, it asserted the nearest double, which is smaller. Naive
``floor(0.99 * 1e6)`` returns 990000 and silently *inflates* the claim, which is
precisely the defect the rounding directions exist to prevent.

VERIFIED: the divergence above is reproduced as a conformance vector and pinned
by tests/test_provenance_quantize.py.

Rounding directions (docs/WIRE_FORMAT.md §4.3) — every one weakens the claim,
so quantization can never inflate a guarantee:

    confidence.value    floor   coverage never overstated
    confidence.alpha    ceil    miscoverage rate never understated
    validity.issued_at  ceil    window never starts earlier than the truth
    validity.expires_at floor   window never ends later than the truth
    interval lo         floor   interval only ever widens
    interval hi         ceil    interval only ever widens
"""
from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction

#: Scale for coverage and alpha: parts per million. 1.0 == 1_000_000.
PPM_SCALE = 1_000_000
PPM_MIN = 0
PPM_MAX = 1_000_000

#: Microseconds since the Unix epoch, UTC. Upper bound is 9999-12-31T23:59:59.999999Z,
#: chosen so every value fits a uint64 and every mainstream date library can render it.
US_MIN = 0
US_MAX = 253_402_300_799_999_999
US_PER_SECOND = 1_000_000

#: Default decimal exponent for confidence-interval endpoints (nano-units).
DEFAULT_INTERVAL_EXP10 = -9
#: Interval mantissas are signed 64-bit.
MANTISSA_ABS_MAX = (1 << 63) - 1


class QuantizationError(ValueError):
    """Raised when a value cannot be reduced, or falls outside its range."""


def exact(x) -> Fraction:
    """Interpret a real-valued input as an exact rational.

    Inputs:  int, float, str, Decimal, or Fraction.
    Outputs: Fraction holding the input's exact value.
    Precondition:  a float input is finite.
    Postcondition: no precision is lost; a float maps to the exact binary value
                   the double holds, a str/Decimal to its exact decimal value.
    """
    if isinstance(x, bool):
        raise QuantizationError("bool is not a real-valued quantity")
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        if not math.isfinite(x):
            raise QuantizationError(f"non-finite value cannot be quantized: {x!r}")
        return Fraction(x)  # exact binary value of the double
    if isinstance(x, Decimal):
        if not x.is_finite():
            raise QuantizationError(f"non-finite Decimal cannot be quantized: {x!r}")
        return Fraction(x)
    if isinstance(x, str):
        try:
            return Fraction(Decimal(x))
        except Exception as exc:
            raise QuantizationError(f"not a decimal literal: {x!r}") from exc
    raise QuantizationError(f"cannot quantize {type(x).__name__}")


def _check_ppm(n: int, what: str) -> int:
    if not (PPM_MIN <= n <= PPM_MAX):
        raise QuantizationError(
            f"{what} = {n} ppm is outside [{PPM_MIN}, {PPM_MAX}]"
        )
    return n


def ratio_to_ppm_floor(x) -> int:
    """Reduce a ratio in [0, 1] to parts-per-million, rounding DOWN.

    Used for ``confidence.value``: quantization never overstates coverage.
    Postcondition: result/1e6 <= exact(x), and result is in [0, 1_000_000].
    """
    return _check_ppm(math.floor(exact(x) * PPM_SCALE), "confidence.value")


def ratio_to_ppm_ceil(x) -> int:
    """Reduce a ratio in [0, 1] to parts-per-million, rounding UP.

    Used for ``confidence.alpha``: quantization never understates miscoverage.
    Postcondition: result/1e6 >= exact(x), and result is in [0, 1_000_000].
    """
    return _check_ppm(math.ceil(exact(x) * PPM_SCALE), "confidence.alpha")


def ppm_to_ratio(n: int) -> float:
    """Render a ppm integer back as a float, for legacy read-side APIs only.

    Precondition:  n in [0, 1_000_000].
    Postcondition: exact for every n whose value is representable; this is a
                   display conversion and is never re-signed.
    """
    _check_ppm(int(n), "ppm")
    return int(n) / PPM_SCALE


def _check_us(n: int, what: str) -> int:
    if not (US_MIN <= n <= US_MAX):
        raise QuantizationError(
            f"{what} = {n} us is outside [{US_MIN}, {US_MAX}] "
            "(0001-01-01T00:00:00Z .. 9999-12-31T23:59:59.999999Z)"
        )
    return n


def seconds_to_us_ceil(x) -> int:
    """Reduce a Unix-epoch time in seconds to microseconds, rounding UP.

    Used for ``validity.issued_at``: the window never starts earlier than truth.
    """
    return _check_us(math.ceil(exact(x) * US_PER_SECOND), "validity.issued_at")


def seconds_to_us_floor(x) -> int:
    """Reduce a Unix-epoch time in seconds to microseconds, rounding DOWN.

    Used for ``validity.expires_at``: the window never ends later than truth.
    """
    return _check_us(math.floor(exact(x) * US_PER_SECOND), "validity.expires_at")


def us_to_seconds(n: int) -> float:
    """Render microseconds back as float seconds, for legacy read-side APIs."""
    _check_us(int(n), "timestamp")
    return int(n) / US_PER_SECOND


def _check_mantissa(m: int, what: str) -> int:
    if abs(m) > MANTISSA_ABS_MAX:
        raise QuantizationError(f"{what} mantissa {m} exceeds signed 64-bit range")
    return m


def to_decimal_floor(x, exp10: int = DEFAULT_INTERVAL_EXP10) -> list:
    """Reduce a real to ``[mantissa, exp10]`` with mantissa rounded DOWN.

    Used for a confidence interval's lower endpoint: the interval only widens.
    Postcondition: mantissa * 10**exp10 <= exact(x).
    """
    m = math.floor(exact(x) / Fraction(10) ** exp10)
    return [_check_mantissa(m, "interval lo"), int(exp10)]


def to_decimal_ceil(x, exp10: int = DEFAULT_INTERVAL_EXP10) -> list:
    """Reduce a real to ``[mantissa, exp10]`` with mantissa rounded UP.

    Used for a confidence interval's upper endpoint: the interval only widens.
    Postcondition: mantissa * 10**exp10 >= exact(x).
    """
    m = math.ceil(exact(x) / Fraction(10) ** exp10)
    return [_check_mantissa(m, "interval hi"), int(exp10)]


def decimal_to_float(pair) -> float:
    """Render a ``[mantissa, exp10]`` pair as a float, for legacy read-side APIs."""
    m, e = int(pair[0]), int(pair[1])
    return float(Fraction(m) * Fraction(10) ** e)
