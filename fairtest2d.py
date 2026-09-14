"""Are the nine seed signatures boilerplate or transients? And what did the
boundary suppress outside receipts vs keep?"""
import sys, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW
SPLIT = datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp()
receipts = sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(), r.get("displayName",""))
                  for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
seed_r = [r for r in receipts if r[0] < SPLIT]
ad,_ = detect(LOG); hands = default_hands(); events = []
for ev in read(LOG, ad):
    if ev.ident not in INSTALLERS: continue
    t = utc(ev.ts)
    if t is None: continue
    a,dem,held,obs,d,case,acts = rule(encode(ev), hands=hands)
    events.append((t, disposition(case,held,a), signature(ev), ev.message[:84]))
events.sort(key=lambda e:e[0]); times=[e[0] for e in events]
def window(t): return range(bisect.bisect_left(times,t-WINDOW), bisect.bisect_right(times,t+30))

# PREVALENCE: in how many of the 96 seed installs does each signature page?
per_sig_installs = collections.defaultdict(set); text = {}
for k,(t,_) in enumerate(seed_r):
    for i in window(t):
        if events[i][1] in ("page","runbook"):
            per_sig_installs[events[i][2]].add(k); text[events[i][2]] = events[i][3]
print(f"  THE NINE SEED SIGNATURES -- prevalence across {len(seed_r)} successful installs")
print(f"  {'installs':>9s}  line")
for sig, ks in sorted(per_sig_installs.items(), key=lambda t:-len(t[1])):
    print(f"  {len(ks):>4}/{len(seed_r):<4}  {text[sig]}")
routine = set(per_sig_installs)

# OUTSIDE RECEIPTS, 2026: what got suppressed, what got kept
inwin = {i for t,_ in receipts for i in window(t)}
dd = Dedup(window=300); sup = collections.Counter(); kept = collections.Counter()
for i,(t,disp,sig,msg) in enumerate(events):
    hidden = dd.seen(sig, t)
    if disp in ("page","runbook") and not hidden and i not in inwin and t >= SPLIT:
        (sup if sig in routine else kept)[msg] += 1
print(f"\n  OUTSIDE ANY RECEIPT, 2026 -- pages the boundary SUPPRESSED ({sum(sup.values()):,}):")
for m,c in sup.most_common(4): print(f"    {c:>5}x  {m}")
print(f"\n  OUTSIDE ANY RECEIPT, 2026 -- pages the boundary KEPT ({sum(kept.values()):,}, {len(kept)} distinct):")
for m,c in kept.most_common(8): print(f"    {c:>5}x  {m}")
