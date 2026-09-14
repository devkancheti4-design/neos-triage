"""
neos -- triage a structured event stream by exact law. No model in the loop.

    python3 -m neos.cli /var/log/install.log
    python3 -m neos.cli --json /var/log/syslog > verdicts.json
    tail -f /var/log/app.log | python3 -m neos.cli -

Every disposition is a few bit operations over a byte. Nothing is trained,
nothing is sampled, and the same laws run here as in the mail agent -- see
ALERTS.md for what that does and does not buy.
"""
import sys, json, collections, argparse, os
from .stream import detect, read, ADAPTERS, Event
from .triage import (encode, signature, Dedup, rule, default_hands,
                     HAZARD_WHY, DOUBT_WHY)
from .laws import ACT, DEM
from .measure import HAZARD_NAMES, DOUBT_NAMES, deciding_hazards, deciding_doubts

MIN_PARSE = 0.50


def disposition(case, held, act):
    if act == 0:   return "no-call"
    if held:       return "held"
    if case.get("flags"):   return "page"
    if case.get("plan"):    return "runbook"
    if case.get("ticket"):  return "ticket"
    if case.get("archive"): return "suppress"
    return "UNDISPOSED"        # tests prove unreachable; if it prints, tell me


def events(path, adapter):
    if path == "-":
        ad = adapter or ADAPTERS[0]
        prev = None
        for line in sys.stdin:
            e = ad.parse(line.rstrip("\n"))
            if e is None:
                if prev is not None: prev.message += " " + line.strip()
                continue
            if prev is not None: yield prev
            prev = e
        if prev is not None: yield prev
    else:
        yield from read(path, adapter)


def verdicts(path, adapter, hands, budget, dedup_cap, stats=None,
             window=300.0, every=20, routine=None):
    """One pass. Yields a verdict dict per DISTINCT event, and the dedup so
    the caller can report repeats. Shared by triage and label: if they used
    separate loops the labelled sample would not describe the actual run."""
    # stats is MUTABLE ON PURPOSE. Reading the total off the last yielded
    # value undercounts by however many duplicates trail the final distinct
    # event -- 914 of 215,089 on one real file, silently.
    stats = {} if stats is None else stats
    stats.setdefault("events", 0)
    dd, spent, n = Dedup(cap=dedup_cap, window=window, every=every), 0.0, 0
    stats["dedup"] = dd
    for ev in events(path, adapter):
        n += 1
        stats["events"] = n
        # RULE FIRST, DEDUP SECOND. The laws cost zero tokens, so there was
        # never a reason to put a hash set in front of them -- and doing so
        # gave 0% incident recall against independent ground truth, because
        # a recurring failure was ruled once in 2024 and never again.
        # Dedup belongs in front of the EXPENSIVE step (decode), which is
        # what it still gates, not in front of the free one.
        pkt = encode(ev)
        act, dem, held, obs, doubt, case, acts = rule(
            pkt, hands=hands, budget_used=spent, budget_cap=budget)
        spent += len(acts)
        sig = signature(ev)
        if routine and sig in routine:
            # ORACLE-SEEDED BOUNDARY. The laws already ruled above; this only
            # decides whether a ruling on known boilerplate is shown. It
            # cannot promote anything, only hide what an oracle proved routine.
            stats["routine"] = stats.get("routine", 0) + 1
            continue
        if dd.seen(sig, ev.epoch):
            stats["ruled_then_deduped"] = stats.get("ruled_then_deduped", 0) + 1
            continue
        yield n, dd, {
            "disposition": disposition(case, held, act),
            "act": ACT[act], "demand": DEM[dem], "ident": ev.ident,
            "ts": ev.ts, "level": ev.level, "message": ev.message[:400],
            "hazards": [HAZARD_NAMES[i] for i in range(8) if obs >> i & 1],
            "doubts": [DOUBT_NAMES[i] for i in range(8) if doubt >> i & 1],
            "labels": case.get("labels", []), "confidence": pkt.confidence,
        }


def resolve(path, fmt):
    """Adapter or a refusal. Below MIN_PARSE this returns None rather than
    handing back a confident-looking result over 3% of a stream."""
    if fmt:
        return next(x for x in ADAPTERS if x.name == fmt), 1.0
    if path == "-":
        return ADAPTERS[0], 1.0
    if not os.path.exists(path):
        print(f"neos: no such file: {path}", file=sys.stderr)
        return None, 0.0
    ad, rate = detect(path)
    if ad is None or rate < MIN_PARSE:
        print(f"neos: cannot read this stream -- best adapter "
              f"{ad.name if ad else 'none'} matched {100*rate:.1f}% of sampled "
              f"lines (need {100*MIN_PARSE:.0f}%).\n      Pass --format "
              f"explicitly, or add an adapter to neos/stream.py.", file=sys.stderr)
        return None, rate
    return ad, rate


def cmd_label(a):
    """Draw a stratified sample for a human to label."""
    from .label import draw
    ad, rate = resolve(a.path, a.format)
    if ad is None:
        return 3
    rows = [v for _, _, v in verdicts(a.path, ad, default_hands(),
                                      a.budget, a.dedup_cap)]
    sample, strata = draw(rows, per_stratum=a.per_stratum, seed=a.seed)
    with open(a.out, "w") as f:
        f.write(json.dumps({"_strata": strata, "source": a.path,
                            "seed": a.seed}) + "\n")
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n  wrote {a.out}  --  {len(sample):,} events sampled from "
          f"{len(rows):,} distinct")
    print(f"  stratified, so the rare classes are represented:")
    for d, n in sorted(strata.items()):
        got = sum(1 for r in sample if r["disposition"] == d)
        print(f"    {d:12s} {got:>4,} sampled of {n:>8,} in the stream")
    print(f"\n  Now fill in the \"human\" field on each line with one of:")
    print(f"    ok        the tool was right")
    print(f"    page / runbook / ticket / suppress   what it SHOULD have been")
    print(f"\n  Then:  neos score {a.out}\n")
    return 0


def cmd_seed(a):
    from .seed import seed, load_known_good
    ad, rate = resolve(a.path, a.format)
    if ad is None:
        return 3
    kg = load_known_good(a.known_good)
    if not kg:
        print("neos: no timestamps could be read from --known-good", file=sys.stderr)
        return 2
    rows = []
    hands = default_hands()
    for ev in events(a.path, ad):
        pkt = encode(ev)
        act, dem, held, obs, doubt, case, acts = rule(pkt, hands=hands)
        rows.append((ev.epoch, disposition(case, held, act), signature(ev), ev.message))
    out = seed(rows, kg, a.window, a.min_prevalence)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n  {len(kg):,} known-good outcomes, {out['known_good_windows']:,} with events "
          f"in a {a.window:.0f}s window")
    print(f"  {len(out['routine'])} signatures marked ROUTINE (paged in >= "
          f"{100*a.min_prevalence:.0f}% of known-good windows):")
    for r in out["routine"]:
        print(f"    {r['in_windows']:>4}/{out['known_good_windows']:<4} {r['example'][:70]}")
    if out["rejected_as_transient"]:
        print(f"  {len(out['rejected_as_transient'])} paged inside a window but too rarely "
              f"to be boilerplate -- KEPT as real:")
        for r in out["rejected_as_transient"][:6]:
            print(f"    {r['in_windows']:>4}/{out['known_good_windows']:<4} {r['example'][:70]}")
    print(f"\n  wrote {a.out}.  Apply with:  neos {a.path} --routine {a.out}\n")
    return 0


def cmd_score(a):
    from .label import score
    return score(a.path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    SUB = {"triage", "label", "score", "seed"}
    if not argv or (argv[0] not in SUB and not argv[0].startswith("-")):
        argv = ["triage"] + argv           # `neos foo.log` still means triage
    elif argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["triage"] + argv

    top = argparse.ArgumentParser(prog="neos", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="score a labelled review file")
    sc.add_argument("path", help="review file written by `neos label`")

    lb = sub.add_parser("label", help="draw a stratified sample for a human")
    lb.add_argument("path", help="log file, or - for stdin")
    lb.add_argument("-o", "--out", default="review.jsonl")
    lb.add_argument("--per-stratum", type=int, default=40,
                    help="events sampled per disposition (default 40)")
    lb.add_argument("--seed", type=int, default=0)
    lb.add_argument("--format", choices=[x.name for x in ADAPTERS])
    lb.add_argument("--dedup-cap", type=int, default=200_000)
    lb.add_argument("--budget", type=float, default=1e9)

    sd = sub.add_parser("seed", help="turn known-good outcomes into a routine set")
    sd.add_argument("path", help="log file")
    sd.add_argument("--known-good", required=True,
                    help="timestamps of known-good outcomes, one per line; "
                         "or a macOS InstallHistory.plist")
    sd.add_argument("-o", "--out", default="routine.json")
    sd.add_argument("--window", type=float, default=600.0,
                    help="seconds before each outcome to attribute (default 600)")
    sd.add_argument("--min-prevalence", type=float, default=0.05,
                    help="fraction of known-good windows a signature must page in "
                         "to count as boilerplate (default 0.05, measured)")
    sd.add_argument("--format", choices=[x.name for x in ADAPTERS])

    ap = sub.add_parser("triage", help="rule on a stream (default)")
    ap.add_argument("path", help="log file, or - for stdin")
    ap.add_argument("--routine", help="routine.json from `neos seed`; hides "
                    "signatures an oracle proved routine")
    ap.add_argument("--format", choices=[a.name for a in ADAPTERS],
                    help="force an adapter instead of detecting one")
    ap.add_argument("--json", action="store_true", help="one JSON verdict per line")
    ap.add_argument("--only", choices=["page", "runbook", "ticket", "suppress", "held"],
                    help="print only this disposition (with --json)")
    ap.add_argument("--dedup-cap", type=int, default=200_000)
    ap.add_argument("--window", type=float, default=300.0,
                    help="seconds; a signature surfaces once per window "
                         "(0 disables windowing). THE SAFETY DIAL: too long "
                         "and independent incidents look like one repeat -- "
                         "at infinity this tool scored 0%% incident recall. "
                         "Too short and nothing dedupes. Default 300.")
    ap.add_argument("--realert-every", type=int, default=20,
                    help="when a stream carries no usable timestamp, surface "
                         "every Nth repeat. Bounds how many hide in a row.")
    ap.add_argument("--budget", type=float, default=1e9,
                    help="hands per run before SPENT narrows routing")
    ap.add_argument("--why", action="store_true", help="explain each verdict")
    a = top.parse_args(argv)
    if a.cmd == "score":
        return cmd_score(a)
    if a.cmd == "label":
        return cmd_label(a)
    if a.cmd == "seed":
        return cmd_seed(a)

    adapter, rate = resolve(a.path, a.format)
    if adapter is None:
        return 3 if os.path.exists(a.path) or a.path == "-" else 2

    hands = default_hands()
    routine = None
    if getattr(a, "routine", None):
        from .seed import load_routine
        routine = load_routine(a.routine)
    out, stats = collections.Counter(), {}
    for _n, dd, v in verdicts(a.path, adapter, hands, a.budget, a.dedup_cap,
                              stats, a.window, a.realert_every, routine):
        d = v["disposition"]
        out[d] += 1
        if a.json:
            if a.only and d != a.only:
                continue
            print(json.dumps(v, ensure_ascii=False))
        elif a.why and d in ("page", "runbook", "held"):
            obs = doubt = 0
            ev = type("E", (), {"ident": v["ident"], "message": v["message"]})
            act = ACT.index(v["act"]); dem = DEM.index(v["demand"])
            hz = [(h, HAZARD_WHY[HAZARD_NAMES.index(h)]) for h in v["hazards"]]
            db = [(x, DOUBT_WHY[DOUBT_NAMES.index(x)]) for x in v["doubts"]]
            print(f"  [{d}] {v['ident']}: {v['message'][:90]}")
            print(f"        opened {ACT[act]}"
                  + (f" because {hz[0][1]}" if hz else "")
                  + f"; demands {DEM[dem]}"
                  + (f" because {db[0][1]}" if db else "") + ".")

    n, dd = stats.get("events", 0), stats.get("dedup")
    if a.json:
        return 0
    if not n:
        print("neos: no events read", file=sys.stderr); return 1
    uniq = sum(out.values())
    out["deduped"] = n - uniq - stats.get("routine", 0)
    P = lambda c, t: f"{c:>9,}  {100*c/t:6.2f}%" if t else f"{c:>9,}       -"
    print(f"\n  {a.path}   adapter={adapter.name if adapter else 'stdin'}"
          + (f"  ({100*rate:.1f}% parsed)" if a.path != "-" else ""))
    print(f"  {n:,} events -> {uniq:,} distinct\n")
    print(f"    {'deduped (hash set, not a law)':32s} {P(out['deduped'], n)}")
    if stats.get("routine"):
        print(f"    {'routine (oracle-seeded boundary)':32s} {P(stats['routine'], n)}")
    for d in ("suppress", "ticket", "page", "runbook", "held", "no-call",
              "UNDISPOSED"):
        if out[d]:
            print(f"    {d:32s} {P(out[d], uniq)}"
                  + ("   <-- BUG: report this" if d == "UNDISPOSED" else ""))
    words = out["runbook"]
    print(f"\n    events that ever become words     {words:>9,}  "
          f"{100*words/n:6.4f}% of the stream")
    if out["held"] == 0:
        print(f"\n    DECLINE did not fire on this stream. With {len(hands)} "
              f"hands available the refusal")
        print(f"    path engages only when a round is short of voices -- it "
              f"does fire on other")
        print(f"    streams (durable state changes demanding FULL). Not a pass; "
              f"just untriggered.")
    print(f"    dedup window {a.window:.0f}s"
          + (f", re-alert every {a.realert_every} when a stream has no time"
             if a.window else " (windowing OFF)"))
    if dd.loudest(1):
        sig, c = dd.loudest(1)[0]
        print(f"\n    loudest signature repeated {c:,} times")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
