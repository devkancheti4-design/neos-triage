"""
The missing experiment.

Every number this tool produces measures what it DOES. None of them measure
whether it is RIGHT. Suppressing 97% of a stream is only a good result if it
is the correct 97% -- a tool that suppresses 100% also scores 97%.

This module produces the ground truth that is missing, in three steps:

    neos label  <stream> -o review.jsonl      draw a stratified sample
    <a human fills in the "human" field>      the part no code can do
    neos score  review.jsonl                  rates, with intervals

The metric that matters is FALSE SUPPRESSION: events the laws closed that a
human says should have been surfaced. That is the error that loses an
incident, and it is the one a "97% suppressed" headline hides.

Sampling is STRATIFIED, because the dangerous classes are the rare ones. A
uniform sample of 200 events from install.log would contain roughly 195
suppressions and almost no pages, and would measure the paging decision not
at all. Strata sizes are recorded so the extrapolation back to the stream is
valid rather than decorative.
"""
import json, random, math, collections, sys

LABELS = ("ok", "page", "runbook", "ticket", "suppress")
SEVERITY = {"page": 3, "runbook": 2, "ticket": 1, "suppress": 0, "held": 1,
            "no-call": 0}


def wilson(k, n, z=1.96):
    """95% interval for a proportion. Wilson, not normal-approximation: at
    k=0, n=40 the normal approximation returns [0, 0] and would let this
    report 'zero false suppressions' with total confidence."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z / d * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, max(0.0, c - h), min(1.0, c + h))


def draw(rows, per_stratum=40, seed=0):
    """Stratified by disposition. Rare classes are sampled as heavily as the
    common ones, which is the whole point."""
    rnd = random.Random(seed)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["disposition"]].append(r)
    sample, strata = [], {}
    for d, items in sorted(by.items()):
        strata[d] = len(items)
        take = items if len(items) <= per_stratum else rnd.sample(items, per_stratum)
        for r in take:
            r = dict(r)
            r["human"] = ""          # <- the human fills this in
            sample.append(r)
    rnd.shuffle(sample)              # so the labeller cannot see the strata
    return sample, strata


def score(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    strata = {}
    for r in rows:
        if r.get("_strata"):
            strata = r["_strata"]
    rows = [r for r in rows if not r.get("_strata")]
    done = [r for r in rows if str(r.get("human", "")).strip()]
    bad = [r for r in done if r["human"].strip() not in LABELS]
    if bad:
        print(f"  {len(bad)} rows have a label that is not one of {LABELS}:",
              file=sys.stderr)
        for r in bad[:5]:
            print(f"    {r['human']!r}  on: {r['message'][:60]}", file=sys.stderr)
        return 2
    if not done:
        print(f"  nothing labelled yet. Fill in the \"human\" field of "
              f"{path} with one of {LABELS}\n  (\"ok\" = the tool was right).",
              file=sys.stderr)
        return 1

    print(f"\n  {len(done):,} of {len(rows):,} sampled events labelled"
          + (f"   ({100*len(done)/len(rows):.0f}%)" if rows else ""))
    byd = collections.defaultdict(list)
    for r in done:
        byd[r["disposition"]].append(r)

    print(f"\n  {'tool said':12s} {'labelled':>9s} {'agreed':>7s} "
          f"{'rate':>7s}  {'95% interval':>16s}   in stream")
    print("  " + "-" * 74)
    total_wrong = 0
    for d in sorted(byd):
        rs = byd[d]
        agree = sum(1 for r in rs if r["human"].strip() == "ok")
        total_wrong += len(rs) - agree
        p, lo, hi = wilson(agree, len(rs))
        n_stream = strata.get(d, 0)
        print(f"  {d:12s} {len(rs):>9,} {agree:>7,} {100*p:>6.1f}%  "
              f"[{100*lo:>5.1f}%, {100*hi:>5.1f}%]   {n_stream:>9,}")

    # ---- the number that matters -------------------------------------
    sup = byd.get("suppress", []) + byd.get("no-call", [])
    if sup:
        missed = [r for r in sup if r["human"].strip() not in ("ok", "suppress")]
        p, lo, hi = wilson(len(missed), len(sup))
        n_sup = strata.get("suppress", 0) + strata.get("no-call", 0)
        print(f"\n  FALSE SUPPRESSION -- the error that loses an incident")
        print(f"    {len(missed)} of {len(sup)} labelled suppressions should "
              f"have been surfaced")
        print(f"    rate {100*p:.1f}%   95% CI [{100*lo:.1f}%, {100*hi:.1f}%]")
        if n_sup:
            print(f"    extrapolated to the stream: {lo*n_sup:,.0f} to "
                  f"{hi*n_sup:,.0f} of {n_sup:,} suppressed events")
        if len(missed):
            print(f"\n    what it wrongly closed:")
            for r in missed[:6]:
                print(f"      -> {r['human']:9s} {r['message'][:74]}")
        if hi > 0.01:
            print(f"\n    UPPER BOUND IS {100*hi:.1f}%. Not safe as a decider "
                  f"until this interval is tight AND low.")
        elif len(sup) < 30:
            print(f"\n    Only {len(sup)} suppressions labelled -- the interval "
                  f"is wide because the sample is small, not because the tool "
                  f"is good. Label more.")

    pages = byd.get("page", []) + byd.get("runbook", [])
    if pages:
        noise = [r for r in pages if r["human"].strip() == "suppress"]
        p, lo, hi = wilson(len(noise), len(pages))
        print(f"\n  FALSE PAGE -- the error that burns the operator")
        print(f"    {len(noise)} of {len(pages)} pages/runbooks were noise: "
              f"{100*p:.1f}%  95% CI [{100*lo:.1f}%, {100*hi:.1f}%]")
    print()
    return 0
