"""
FAIR TEST 2: false-page rate, on the stream the economics rest on.

FAIR.md measured incident recall (71.2%) but could not measure false-page
rate: its oracle had no clean runs. This one has 167.

GROUND TRUTH IS NOT MINE. /Library/Receipts/InstallHistory.plist is macOS's
own record of installs that COMPLETED, written by the installer framework,
not by the log and not by this tool. The tool never reads it.

PRE-REGISTERED before looking at any output:

  ROUTINE     an install with a receipt. The events its installer process
              emitted in the WINDOW seconds before the receipt are routine
              by definition -- the install succeeded.
  FALSE PAGE  the tool paged or wrote a runbook on >=1 event of that install
  TICKET      queued, not paged. Reported separately, not counted as a page.

  Metric: FALSE PAGE RATE = installs falsely paged / installs with receipts.

DECLARED WEAKNESS, stated first: a successful install can still contain a
real transient error that a human would want to see. So some "false" pages
may be right. This measures pages on installs that SUCCEEDED, which is the
upper bound on nuisance -- not proof that each page was wrong.
"""
import sys, re, pathlib, plistlib, datetime, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, default_hands
from neos.cli import disposition
from neos.label import wilson

LOG, RECEIPTS, WINDOW = "/var/log/install.log", "/Library/Receipts/InstallHistory.plist", 600
INSTALLERS = {"softwareupdated", "installer", "Installer", "appstoreagent",
              "XProtectUpdateService", "bootinstalld", "installd", "system_installd",
              "suhelperd", "storedownloadd", "nbagent", "mobileassetd"}
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})([-+]\d{2})(?::?(\d{2}))?")

def utc(ts):
    m = TS.match(ts or "")
    if not m: return None
    d = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    off = int(m.group(2)) * 3600 + (int(m.group(3) or 0) * 60) * (1 if m.group(2)[0] == "+" else -1)
    return (d - datetime.timedelta(seconds=off)).replace(tzinfo=datetime.timezone.utc).timestamp()

def main():
    # SNAPSHOT FIRST. The fsck oracle in FAIR.md was truncated to zero bytes
    # by the OS the day after it was measured, and that result can no longer
    # be reproduced from this machine. Oracles are ephemeral; the test keeps
    # its own copy from the day of measurement.
    snap = pathlib.Path(__file__).resolve().parent / "oracles/install_receipts.json"
    if snap.exists():
        import json as _j
        receipts = [(datetime.datetime.fromisoformat(r["date"]).timestamp(), r["processName"], "")
                    for r in _j.load(open(snap))["receipts"]]
    else:
        receipts = [(r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(),
                     r.get("processName", ""), r.get("displayName", ""))
                    for r in plistlib.load(open(RECEIPTS, "rb")) if "date" in r]
    receipts.sort()
    print(f"  ORACLE  {len(receipts)} receipts (InstallHistory.plist, never seen by the tool)")

    # ---- one pass, the tool as shipped, NO dedup: every event must attribute
    ad, rate = detect(LOG)
    hands = default_hands()
    events = []
    for ev in read(LOG, ad):
        if ev.ident not in INSTALLERS: continue
        t = utc(ev.ts)
        if t is None: continue
        a, dem, held, obs, d, case, acts = rule(encode(ev), hands=hands)
        events.append((t, ev.ident, disposition(case, held, a), ev.message[:90]))
    events.sort()
    print(f"  STREAM  {len(events):,} installer-process events in install.log ({100*rate:.0f}% parsed)")

    # ---- attribute events to receipts
    import bisect
    times = [e[0] for e in events]
    matched = falsely_paged = ticketed = 0
    examples = collections.Counter(); ex_lines = []
    for t, proc, name in receipts:
        lo, hi = bisect.bisect_left(times, t - WINDOW), bisect.bisect_right(times, t + 30)
        win = events[lo:hi]
        if not win: continue
        matched += 1
        disps = [e[2] for e in win]
        if any(dp in ("page", "runbook") for dp in disps):
            falsely_paged += 1
            for e in win:
                if e[2] in ("page", "runbook"):
                    examples[e[3]] += 1
                    if len(ex_lines) < 5: ex_lines.append((name[:28], e[2], e[3]))
        if any(dp == "ticket" for dp in disps): ticketed += 1

    p, lo, hi = wilson(falsely_paged, matched)
    print(f"\n  RESULT  installs with events in window   {matched:>4} of {len(receipts)}")
    print(f"          falsely paged / runbook'd        {falsely_paged:>4}")
    print(f"          FALSE PAGE RATE            {100*p:6.1f}%   95% CI [{100*lo:.1f}%, {100*hi:.1f}%]")
    pt, lt, ht = wilson(ticketed, matched)
    print(f"          (ticketed, not paged)      {100*pt:6.1f}%   95% CI [{100*lt:.1f}%, {100*ht:.1f}%]")
    if ex_lines:
        print(f"\n  what it paged on, inside SUCCESSFUL installs:")
        for name, dp, msg in ex_lines: print(f"    [{dp:7s}] {name:28s} {msg[:70]}")
        print(f"\n  most repeated false-page line:")
        for msg, c in examples.most_common(3): print(f"    {c:>4}x  {msg[:80]}")

if __name__ == "__main__":
    main()
