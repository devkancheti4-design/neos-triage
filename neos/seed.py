"""
Turn an oracle into a boundary.

    neos seed app.log --known-good outcomes.txt -o routine.json
    neos app.log --routine routine.json

An ORACLE here is any independent record of outcomes the stream itself
does not carry: install receipts, exit codes, a deploy ledger, a ticket
system's "resolved as not-a-bug". You give it the timestamps of KNOWN-GOOD
outcomes. Events the tool paged on inside those windows were, by definition,
paged on a success.

But not every such page is noise. A real failure can land in the window of
an unrelated success -- measured: 3 of 9 signatures seeded that way were
genuine install failures. So a signature is ROUTINE only if it paged inside
a large fraction of known-good windows. Boilerplate appears in most
successes; a transient appears in a few. The threshold is the smallest
value at which nothing real is hidden, and the default came from that
measurement, not from taste.

Measured on install.log, time-split so the test never saw the seed:
    false-page rate   64.8% -> 11.3%   (71 unseen installs)
    real failures hidden          0
    decode tokens     2,843 -> 280     (97.6% saving vs 75.8%)
    laws touched                  0

This is boundary work. The laws are not consulted, not adjusted, and not
told. They rule exactly as before on everything that reaches them.
"""
import json, bisect, collections, datetime, pathlib
from .stream import parse_ts

DEFAULT_WINDOW = 600.0      # seconds before a known-good outcome
DEFAULT_MIN_PREV = 0.05     # fraction of known-good windows a signature must page in


def load_known_good(path):
    """Timestamps of known-good outcomes, as UTC epoch seconds.

    One timestamp per line in any format parse_ts reads; or a macOS
    InstallHistory.plist, which is the worked example and convenient."""
    p = pathlib.Path(path)
    if p.suffix == ".plist":
        import plistlib
        rec = plistlib.load(open(p, "rb"))
        return sorted(r["date"].replace(tzinfo=datetime.timezone.utc).timestamp()
                      for r in rec if "date" in r)
    out = []
    for line in open(p, errors="replace"):
        t = parse_ts(line.strip())
        if t is not None:
            out.append(t)
    return sorted(out)


def seed(events, known_good, window=DEFAULT_WINDOW, min_prevalence=DEFAULT_MIN_PREV):
    """events: iterable of (epoch, disposition, signature_bytes, message).
    Returns a routine set with its provenance, so it can be audited."""
    ev = sorted((e for e in events if e[0] is not None), key=lambda e: e[0])
    times = [e[0] for e in ev]
    hit = collections.defaultdict(set); text = {}
    n_win = 0
    for k, t in enumerate(known_good):
        lo, hi = bisect.bisect_left(times, t - window), bisect.bisect_right(times, t + 30)
        if lo == hi:
            continue
        n_win += 1
        for i in range(lo, hi):
            _, disp, sig, msg = ev[i]
            if disp in ("page", "runbook"):
                hit[sig].add(k); text.setdefault(sig, msg[:120])
    routine, rejected = [], []
    for sig, ks in hit.items():
        prev = len(ks) / max(1, n_win)
        row = {"signature": sig.hex(), "prevalence": round(prev, 4),
               "in_windows": len(ks), "example": text[sig]}
        (routine if prev >= min_prevalence else rejected).append(row)
    routine.sort(key=lambda r: -r["prevalence"]); rejected.sort(key=lambda r: -r["prevalence"])
    return {"routine": routine, "rejected_as_transient": rejected,
            "known_good_windows": n_win, "window_seconds": window,
            "min_prevalence": min_prevalence}


def load_routine(path):
    d = json.load(open(path))
    return {bytes.fromhex(r["signature"]) for r in d.get("routine", [])}
