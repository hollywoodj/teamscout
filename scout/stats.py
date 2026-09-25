"""Small statistical primitives (stdlib only).

Everything here is deliberately simple and transparent: captains need to be
able to trust (and argue with) every number on the scouting board.
"""

import math
import statistics


def binom_z(wins, n):
    """Approximate z-score of a W/L record against a fair 50% coin.

    z = (wins - n/2) / (sqrt(n)/2).  |z| >= 1.65 is ~90% two-sided evidence
    the record isn't luck. Normal approximation — fine for n >= 10.
    """
    if not n or n < 1:
        return None
    return (wins - n / 2) / (math.sqrt(n) / 2)


MIN_PEERS_FOR_Z = 10  # MAD below this is mostly noise (see robust_z)


def family_z(n_tests, family_alpha=0.10):
    """Two-sided z bar holding the FAMILY-wise error rate across n_tests.

    A 1.65 cutoff is calibrated for testing one player. Run the same test over
    a 100-player pool and ~10 clear it on luck alone. Bonferroni splits the
    budget: family_alpha becomes the chance of ANY false flag on the board,
    not the chance per player. Returns None for n_tests < 1.
    """
    if n_tests < 1:
        return None
    return statistics.NormalDist().inv_cdf(1 - family_alpha / n_tests / 2)


def robust_z(x, peer_values):
    """z-score of x against peers using median/MAD (outlier-resistant).

    Needs MIN_PEERS_FOR_Z peers: a MAD built from a handful of points is
    itself mostly noise, and it sits in the denominator — one accidentally
    tight peer group manufactures a huge z. Returns None when there aren't
    enough peers or the peers have no spread.
    """
    if x is None or len(peer_values) < MIN_PEERS_FOR_Z:
        return None
    med = statistics.median(peer_values)
    mad = statistics.median(abs(v - med) for v in peer_values)
    if mad == 0:
        return None
    return 0.6745 * (x - med) / mad


def ivw_mean(estimates):
    """Inverse-variance weighted mean of (value, sigma) pairs.

    Returns (mean, combined_sigma) or (None, None) if no usable estimates.
    """
    pairs = [(v, s) for v, s in estimates if v is not None and s]
    if not pairs:
        return None, None
    wsum = sum(1 / s ** 2 for _, s in pairs)
    mean = sum(v / s ** 2 for v, s in pairs) / wsum
    return mean, math.sqrt(1 / wsum)


def wilson_lower(wins, n, z=1.28):
    """Wilson score lower bound for a win probability (default ~90% one-sided).

    'Their solo WR is at least X%' with sample size baked in.
    """
    if not n:
        return None
    p = wins / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return (centre - spread) / denom


def _log_fact(n):
    total = 0.0
    for i in range(2, n + 1):
        total += math.log(i)
    return total


def _log_binom(n, k):
    if k < 0 or k > n:
        return float("-inf")
    return _log_fact(n) - _log_fact(k) - _log_fact(n - k)


def fisher_exact(a, b, c, d):
    """Two-sided Fisher's exact p-value for the 2x2 table [[a, b], [c, d]].

    Integer counts only. Returns None if the table is empty. Uses the
    standard 'sum tables at least as unlikely as the observed one' definition,
    so a captain can paste the same W-L split into a calculator and match it.
    """
    cells = (a, b, c, d)
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in cells):
        return None
    n = a + b + c + d
    if n == 0:
        return None
    row1 = a + b
    col1 = a + c

    def logp(aa):
        cc = col1 - aa
        return _log_binom(row1, aa) + _log_binom(n - row1, cc) - _log_binom(n, col1)

    log_obs = logp(a)
    lo = max(0, row1 + col1 - n)
    hi = min(row1, col1)
    total = 0.0
    for aa in range(lo, hi + 1):
        lp = logp(aa)
        if lp <= log_obs + 1e-9:
            total += math.exp(lp)
    return min(1.0, total)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
