"""
Can the oracle FIX the boundary, without circularity?

Time split. Receipts before 2026-01-01 SEED a set of routine signatures:
lines that surfaced as page/runbook inside successful installs. Receipts
from 2026 on are the TEST -- never seen during seeding. If the false-page
rate on 2026 installs falls, the oracle has been turned into a boundary,
and the laws still have not been touched.

The counter-metric that keeps this honest: pages OUTSIDE receipt windows.
A filter that suppresses everything scores 0% false-page trivially. It
must keep paging on activity that has no receipt -- the unknown and the
failed -- or it has just gone blind.
"""
import sys, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from neos.label import wilson
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW

SPLIT = datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp()
receipts = sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(), r.get("displayName",""))
                  for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
seed_r = [r for r in receipts if r[0] <  SPLIT]
test_r = [r for r in receipts if r[0] >= SPLIT]
print(f"  SPLIT   seed on {len(seed_r)} receipts before 2026, test on {len(test_r)} from 2026")

ad, _ = detect(LOG); hands = default_hands()
events = []
for ev in read(LOG, ad):
    if ev.ident not in INSTALLERS: continue
    t = utc(ev.ts)
    if t is None: continue
    a, dem, held, obs, d, case, acts = rule(encode(ev), hands=hands)
    events.append((t, disposition(case, held, a), signature(ev), ev))
events.sort(key=lambda e: e[0]); times = [e[0] for e in events]
def window(t): return range(bisect.bisect_left(times, t-WINDOW), bisect.bisect_right(times, t+30))

# ---- SEED: signatures that paged inside pre-2026 successful installs
routine = collections.Counter()
for t, _ in seed_r:
    for i in window(t):
        if events[i][1] in ("page","runbook"): routine[events[i][2]] += 1
print(f"  SEED    {len(routine)} distinct signatures paged inside successful installs")

# ---- TEST on 2026 receipts, before and after the boundary
def measure(suppress):
    dd = Dedup(window=300); surfaced = {}
    for i, (t, disp, sig, ev) in enumerate(events):
        hidden = dd.seen(sig, ev.epoch) or (suppress and sig in routine)
        surfaced[i] = (disp, hidden)
    m = fp = 0
    for t, _ in test_r:
        w = list(window(t))
        if not w: continue
        m += 1
        if any(surfaced[i][0] in ("page","runbook") and not surfaced[i][1] for i in w): fp += 1
    inwin = {i for t,_ in test_r for i in window(t)}
    out_pages = sum(1 for i,(d,h) in surfaced.items()
                    if d in ("page","runbook") and not h and i not in inwin and events[i][0] >= SPLIT)
    return m, fp, out_pages

for label, sup in (("laws alone", False), ("laws + oracle-seeded boundary", True)):
    m, fp, outp = measure(sup)
    p, lo, hi = wilson(fp, m)
    print(f"\n  {label}")
    print(f"    false-page rate on 2026 installs   {fp}/{m}  {100*p:5.1f}%  [{100*lo:.1f}%, {100*hi:.1f}%]")
    print(f"    pages retained OUTSIDE receipts    {outp:,}   <- must not go to zero")
