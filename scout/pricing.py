"""The auction premium model — named once, in Python.

The kNN base price lives in :mod:`scout.auction`. The *premium* on top of it (the
top of the board gets bid up, the tail goes for steals; the top 3 at each
position carry a scarcity premium) is genuinely computed in two languages: this
module seeds the values in Python, and the dashboard's JS recomputes them live as
you edit MMRs/roles/captains (see ``rankPremWith`` / ``premWith`` in
report_html). They share only the config control points, so the algorithm itself
could drift silently.

This module is the Python home for that algorithm, and ``pricing_vectors.json``
(generated from :func:`golden_vectors`) is the language-neutral fixture both
sides replay in their own test suites — a drift in either implementation becomes
a failing vector instead of a silent mispricing.
"""

from . import config


def rank_premium(rank, rank_pts=None):
    """Linear interpolation over the rank-premium control points, flat outside
    the ends. ``rank_pts`` defaults to :data:`config.AUCTION_RANK_PREMIUM` but is
    a parameter so the golden fixture can pin the algorithm to frozen points,
    independent of live tuning."""
    pts = rank_pts if rank_pts is not None else config.AUCTION_RANK_PREMIUM
    if rank <= pts[0][0]:
        return pts[0][1]
    for (r0, p0), (r1, p1) in zip(pts, pts[1:]):
        if rank <= r1:
            return p0 + (p1 - p0) * (rank - r0) / (r1 - r0)
    return pts[-1][1]


def combined_premium(mmr, roles, ranked, pos_ranked, rank_pts=None, pos_pts=None):
    """Overall board-rank premium, max()-combined with positional scarcity.

    ``ranked`` is the pool's MMRs sorted descending; ``pos_ranked`` is
    ``{position: descending MMRs}``. A player's overall rank is
    ``1 + count(m > mmr)``; the positional premium applies to the top
    ``len(pos_pts)`` available at each of the player's roles. Mirror of the
    dashboard's JS ``premWith`` — kept in lockstep by ``pricing_vectors.json``.
    """
    pos_pts = pos_pts if pos_pts is not None else config.AUCTION_POS_PREMIUM
    best = rank_premium(1 + sum(1 for m in ranked if m > mmr), rank_pts)
    for pos in roles or ():
        mmrs = pos_ranked.get(pos)
        if mmrs:
            rank = 1 + sum(1 for m in mmrs if m > mmr)
            if rank <= len(pos_pts):
                best = max(best, pos_pts[rank - 1])
    return best


def round5(x):
    """Auction bids resolve to $5; never below the $5 floor."""
    return max(5, int(round(x / 5) * 5))


def pricing_payload():
    """The control points the dashboard's JS reprice needs — config exposed
    through one function so the injection site has a single source."""
    return {"rank": config.AUCTION_RANK_PREMIUM, "pos": config.AUCTION_POS_PREMIUM}


# --------------------------------------------------------------------------
# Golden vectors — the shared cross-language contract
# --------------------------------------------------------------------------
# Frozen control points the fixture is generated against. Deliberately NOT
# config.* so the vectors test the ALGORITHM, not the current tuning: retuning
# config is free, changing the interpolation/combine rule breaks a vector.
_VECTOR_RANK = [[1, 80], [2, 55], [3, 45], [5, 40], [8, 30],
                [12, 15], [16, 8], [22, -5], [28, -15]]
_VECTOR_POS = [40, 25, 12]
# A synthetic descending pool: 30 players 200 MMR apart, top at 6000.
_VECTOR_POOL = [6000 - 200 * i for i in range(30)]


def golden_vectors():
    """Build the golden-vector fixture as a JSON-serialisable dict.

    Every case pins ``(mmr, roles, ranked, pos_ranked) -> premium`` computed by
    :func:`combined_premium` against the frozen control points. Regenerate with
    ``python -m scout.pricing`` after an intentional algorithm change.
    """
    ranked = sorted(_VECTOR_POOL, reverse=True)
    # role 1 = the odd-indexed slice (ranks differ from the overall board); role
    # 4 = a scarce cluster of low-MMR supports, so a tail player can top their
    # position and the positional max()-combine genuinely wins over rank.
    pos_ranked = {1: sorted(_VECTOR_POOL[::2], reverse=True),
                  4: [3000, 2800, 2600]}
    pos_json = {str(p): mmrs for p, mmrs in pos_ranked.items()}
    cases = []

    def case(mmr, roles):
        prem = combined_premium(mmr, roles, ranked, pos_ranked,
                                _VECTOR_RANK, _VECTOR_POS)
        cases.append({"mmr": mmr, "roles": list(roles),
                      "ranked": ranked, "posRanked": pos_json, "premium": prem})

    # overall-rank sweep across the interpolation's endpoints, knees and tail
    for k in (1, 2, 3, 4, 5, 8, 12, 16, 22, 28, 30):
        case(_VECTOR_POOL[k - 1] - 50, [])   # no roles → overall premium only
    # positional cases exercising the max()-combine both ways
    case(6000 - 50, [1])     # near the top: overall rank premium dominates
    case(3100, [4])          # low overall, but #1 at scarce pos 4 → pos wins
    case(3000, [1, 2])       # multi-role, pos 2 has no pool → falls back to rank
    case(1000, [1])          # deep tail: negative rank premium, no pos help
    return {"rank": _VECTOR_RANK, "pos": _VECTOR_POS, "cases": cases}


if __name__ == "__main__":  # regenerate the committed fixture
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "pricing_vectors.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(golden_vectors(), f, indent=2)
    print(f"wrote {path} ({len(golden_vectors()['cases'])} vectors)")
