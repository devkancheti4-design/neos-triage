"""
The laws. Bit-identical to route.c / joint2.c -- verified by tests/test_laws.py
against the compiled C kernels over all 256 inputs.

Nothing here is trained, tuned, or fitted. Every function is a handful of bit
operations over a byte, and every one has been checked against its whole
input domain. That is the entire reason this agent can be audited.
"""

ACT  = ["NONE", "ONE", "PAIR", "RESV", "ROOM"]
DEM  = ["PASS", "SELF", "AGREE", "RESV", "FULL", "DECLINE"]
HAVE = [0, 1, 2, 3, 4, 0]     # voices a round of this act puts on the line
NEED = [0, 1, 2, 3, 3, 0]     # voices a check of this demand consumes
KOF  = [0, 1, 2, 3, 8]        # act -> how many neos actually draft


def route(obs: int) -> int:
    """ROUTE -- the cost axis. Every bit a HAZARD; hazards NARROW.

    An unmeasured world routes narrower and spends less, never wider. The
    room (act 4) is what is LEFT OVER when every measurement completed and
    found nothing missing -- never a default.
    """
    x = obs & 0xFF
    m = ((x & 1) | ((x >> 1) & 1)                                  # bit0 NONE
         | (((x >> 2) & 1) << 1) | (((x >> 3) & 1) << 1)           # bit1 ONE
         | (((x >> 6) & 1) << 1)
         | (((x >> 4) & 1) << 2) | (((x >> 5) & 1) << 2)           # bit2 PAIR
         | (((x >> 7) & 1) << 2)
         | 16)                                                     # bit4 FLOOR
    return (m & -m).bit_length() - 1


def redial(doubt: int) -> int:
    """REDIAL -- the correctness axis. Every bit a DOUBT; doubts WIDEN.

    The exact mirror of route: OR/max where route is OR/min. An unmeasured
    world demands MORE checking, never less.
    """
    y = doubt & 0xFF
    m = ((((y >> 0) & 1) << 1) | (((y >> 2) & 1) << 1)             # bit1 SELF
         | (((y >> 7) & 1) << 1)
         | (((y >> 1) & 1) << 2) | (((y >> 5) & 1) << 2)           # bit2 AGREE
         | (((y >> 6) & 1) << 2)
         | (((y >> 3) & 1) << 4) | (((y >> 4) & 1) << 4)           # bit4 FULL
         | 1)                                                      # bit0 CEILING
    return m.bit_length() - 1


def decline(act: int, dem: int) -> bool:
    """DECLINE -- the only coupling between the two axes.

    Fires when the round that was opened cannot service the check the draft
    demands. Not a threshold: five cells of a 5x5 table, and nothing in it
    was tuned.

    NOTE it is DERIVED, not measured, and it does NOT fold. The two axes fold
    in opposite directions, so a thread can decline when no message in it did
    (52 of 625 combinations). Recompute it at every fold; never OR it upward.
    """
    if act < 0 or act > 4 or dem < 0 or dem > 5:
        return True                                   # fail closed, off domain
    if dem == 5:
        return True      # the demand IS DECLINE. NEED[5] is 0 because a
                         # declined round never proceeds -- inert, not cheap.
                         # Reading it as "costs nothing, so send" is the hole.
    return NEED[dem] > HAVE[act] and act != 0


def fold_route(acts):
    """A thread routes as narrowly as its narrowest part. OR the masks, take
    the lowest bit -- which is min over acts."""
    return min(acts) if acts else 4


def fold_redial(dems):
    """A thread demands as much checking as its most doubtful part."""
    return max(dems) if dems else 0
