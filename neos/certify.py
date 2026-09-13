"""
Certify a law before you bind it to others.

    from neos.certify import certify, report
    report({"my_law": my_act_function})

The generate -> certify -> keep loop is what makes hundreds of laws a compute
budget rather than a career: 1,000 laws certify exhaustively in ~90 seconds.
Nothing here is sampled. Every check runs the whole domain.

WHAT IS CHECKED, and why each one earns its place:

  polarity      A ctz/min ladder NARROWS as evidence accumulates (hazards).
                Its dual, an msb/max ladder, WIDENS (doubts). This is detected
                rather than assumed, because asserting the narrowing property
                on a widening law reports a correct law as broken -- and a
                certifier that discards good laws is worse than none. That
                mistake has been made twice in this project's history.

  total         Every input has an action. A law with a domain hole routes
                something to a reserved value and nothing catches it.

  monotone      More evidence never loosens the ruling (in the law's own
                polarity).

  homomorphic   ACT(a|b) == agg(ACT(a), ACT(b)). THE load-bearing property:
                min of homomorphisms is a homomorphism, so a composition of
                N laws never needs its joint space. 100 laws cost 25,600
                checks; their joint space is 2^800. A law that fails this can
                still pass monotonicity -- measured at 0/60 homomorphic while
                60/60 monotone -- so this is the check that must not be
                skipped, and the one a human reviewer will not perform.
"""

def certify(act, domain: int = 256, bits: int = 8) -> dict:
    """Exhaustive certificate for an integer law `act: int -> int`."""
    rng = range(domain)
    ups = sum(act(a | (1 << i)) > act(a) for a in rng for i in range(bits))
    downs = sum(act(a | (1 << i)) < act(a) for a in rng for i in range(bits))
    widening = ups > downs
    agg = max if widening else min
    mono = all((act(a | (1 << i)) >= act(a)) if widening
               else (act(a | (1 << i)) <= act(a))
               for a in rng for i in range(bits))
    homo = all(act(a | b) == agg(act(a), act(b)) for a in rng for b in rng)
    total = all(isinstance(act(x), int) and act(x) >= 0 for x in rng)
    return {"polarity": "widening" if widening else "narrowing",
            "total": total, "monotone": mono, "homomorphic": homo,
            "composable": bool(total and mono and homo),
            "acts": sorted({act(x) for x in rng})}


def certify_joint(decide, have, need) -> dict:
    """For a joint law like decline(act, demand): the failure that matters is
    FAIL-OPEN -- letting a round proceed with fewer voices than the demand
    requires. That is the one bug in this project's history that was a real
    law bug, and it was fail-open in the fail-closed lane."""
    holes = [(a, d) for a in range(len(have)) for d in range(len(need))
             if have[a] and need[d] and not decide(a, d) and have[a] < need[d]]
    over = [(a, d) for a in range(len(have)) for d in range(len(need))
            if have[a] and need[d] and have[a] >= need[d] and decide(a, d)]
    return {"fail_open": holes, "over_refusal": over,
            "sound": not holes and not over}


def report(laws: dict, domain: int = 256) -> bool:
    """Print a table. Returns True only if every law is composable."""
    print(f"  {'law':24s} {'polarity':10s} {'total':>6s} {'mono':>6s} "
          f"{'homo':>6s} {'composable':>11s}")
    print("  " + "-" * 70)
    ok = True
    for name, fn in laws.items():
        r = certify(fn, domain)
        ok &= r["composable"]
        print(f"  {name:24s} {r['polarity']:10s} {str(r['total']):>6s} "
              f"{str(r['monotone']):>6s} {str(r['homomorphic']):>6s} "
              f"{str(r['composable']):>11s}")
    return ok


if __name__ == "__main__":
    from .laws import route, redial, decline, HAVE, NEED
    ok = report({"route": route, "redial": redial})
    j = certify_joint(decline, HAVE, NEED)
    print(f"\n  decline (joint)  fail-open {len(j['fail_open'])}  "
          f"over-refusal {len(j['over_refusal'])}  sound {j['sound']}")
    raise SystemExit(0 if (ok and j["sound"]) else 1)
