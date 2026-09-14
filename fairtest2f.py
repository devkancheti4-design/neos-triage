"""Corrected seed: a signature is boilerplate only if it paged in >= MIN of
successful seed installs. Sensitivity across thresholds, and a check that
the three real-failure lines SURVIVE the boundary."""
import sys, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from neos.label import wilson
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW
SPLIT = datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp()
receipts = sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(),)
                  for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
seed_r=[r for r in receipts if r[0]<SPLIT]; test_r=[r for r in receipts if r[0]>=SPLIT]
ad,_=detect(LOG); hands=default_hands(); events=[]
for ev in read(LOG, ad):
    if ev.ident not in INSTALLERS: continue
    t=utc(ev.ts)
    if t is None: continue
    a,dem,held,obs,d,case,acts=rule(encode(ev),hands=hands)
    events.append((t,disposition(case,held,a),signature(ev),ev.message[:84]))
events.sort(key=lambda e:e[0]); times=[e[0] for e in events]
def window(t): return range(bisect.bisect_left(times,t-WINDOW),bisect.bisect_right(times,t+30))
prev=collections.defaultdict(set); text={}
for k,(t,) in enumerate(seed_r):
    for i in window(t):
        if events[i][1] in ("page","runbook"): prev[events[i][2]].add(k); text[events[i][2]]=events[i][3]
REAL=[s for s in prev if any(w in text[s] for w in ("had errors preventing","failed pre-install","Will NOT continue"))]
inwin_test={i for (t,) in test_r for i in window(t)}

def run(minfrac):
    routine={s for s,ks in prev.items() if len(ks)/len(seed_r)>=minfrac}
    dd=Dedup(window=300); vis={}
    for i,(t,disp,sig,msg) in enumerate(events):
        vis[i]=(disp, dd.seen(sig,t) or (sig in routine))
    m=fp=0
    for (t,) in test_r:
        w=list(window(t))
        if not w: continue
        m+=1
        if any(vis[i][0] in ("page","runbook") and not vis[i][1] for i in w): fp+=1
    kept=sum(1 for i,(d,h) in vis.items() if d in ("page","runbook") and not h and i not in inwin_test and events[i][0]>=SPLIT)
    hidden_real=[s for s in REAL if s in routine]
    return len(routine), m, fp, kept, hidden_real

print(f"  {len(REAL)} real-failure signatures found inside seed windows (window bleed)\n")
print(f"  {'min prevalence':>15s} {'seed sigs':>10s} {'2026 false-page':>16s} {'95% CI':>16s} {'kept outside':>13s} {'real failures hidden':>21s}")
print("  "+"-"*98)
for mf in (0.0, 0.05, 0.10, 0.20, 0.40):
    n,m,fp,kept,hr=run(mf)
    p,lo,hi=wilson(fp,m)
    flag="  <-- HIDES REAL FAILURES" if hr else ""
    print(f"  {100*mf:>13.0f}% {n:>10d} {fp:>6}/{m:<8} {100*p:>5.1f}%  [{100*lo:4.1f}%,{100*hi:5.1f}%] {kept:>13,} {len(hr):>21d}{flag}")
print("\n  0% = the flawed seed from fairtest2c. The threshold is chosen for the")
print("  smallest value at which no real-failure signature is suppressed.")
