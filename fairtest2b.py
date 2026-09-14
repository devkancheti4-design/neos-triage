"""As deployed (dedup on): what a user sees, and where the decode tokens go."""
import sys, re, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from neos.label import wilson
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW

receipts = sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(), r.get("displayName",""))
                  for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
ad, _ = detect(LOG); hands = default_hands(); dd = Dedup(window=300)
events = []                       # every installer event, with whether it SURFACED
for ev in read(LOG, ad):
    if ev.ident not in INSTALLERS: continue
    t = utc(ev.ts)
    if t is None: continue
    a, dem, held, obs, d, case, acts = rule(encode(ev), hands=hands)
    disp = disposition(case, held, a)
    hidden = dd.seen(signature(ev), ev.epoch)
    events.append((t, disp, hidden))
events.sort(key=lambda e: e[0]); times = [e[0] for e in events]

# per install, as deployed
matched = fp = 0
for t, name in receipts:
    win = events[bisect.bisect_left(times, t-WINDOW):bisect.bisect_right(times, t+30)]
    if not win: continue
    matched += 1
    if any(d in ("page","runbook") and not h for _, d, h in win): fp += 1
p, lo, hi = wilson(fp, matched)
print(f"  AS DEPLOYED (dedup window 300s)")
print(f"    installs falsely paged   {fp}/{matched}   {100*p:.1f}%   95% CI [{100*lo:.1f}%, {100*hi:.1f}%]")

# where the decodes go: runbooks that surfaced, inside vs outside receipt windows
inwin = set()
for t, _ in receipts:
    for i in range(bisect.bisect_left(times, t-WINDOW), bisect.bisect_right(times, t+30)):
        inwin.add(i)
decodes = [(i, e) for i, e in enumerate(events) if e[1] == "runbook" and not e[2]]
inside = sum(1 for i, _ in decodes if i in inwin)
print(f"\n  DECODE TOKENS (runbooks that surfaced, installer processes only)")
print(f"    total decodes            {len(decodes):>6,}")
print(f"    inside successful installs  {inside:>6,}   {100*inside/max(1,len(decodes)):.1f}%  <- spent on non-incidents")
print(f"    outside any receipt      {len(decodes)-inside:>6,}   {100*(len(decodes)-inside)/max(1,len(decodes)):.1f}%")
pages = [(i, e) for i, e in enumerate(events) if e[1] == "page" and not e[2]]
print(f"    pages: {len(pages)} total, {sum(1 for i,_ in pages if i in inwin)} inside successful installs")
