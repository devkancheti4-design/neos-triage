"""Economics with the PREVALENCE-FILTERED seed, at each threshold."""
import sys, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW
SPLIT=datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp()
receipts=sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(),)
                for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
seed_r=[r for r in receipts if r[0]<SPLIT]
ad,_=detect(LOG); hands=default_hands(); allev=[]
for ev in read(LOG,ad):
    a,dem,held,obs,d,case,acts=rule(encode(ev),hands=hands)
    allev.append((utc(ev.ts),ev.ident,disposition(case,held,a),signature(ev),ev.epoch,len(ev.message)))
inst=sorted([e for e in allev if e[1] in INSTALLERS and e[0] is not None],key=lambda e:e[0]); times=[e[0] for e in inst]
prev=collections.defaultdict(set)
for k,(t,) in enumerate(seed_r):
    for i in range(bisect.bisect_left(times,t-WINDOW),bisect.bisect_right(times,t+30)):
        if inst[i][2] in ("page","runbook"): prev[inst[i][3]].add(k)
def account(routine):
    dd=Dedup(window=300); n=len(allev); u=d=ch=0
    for t,ident,disp,sig,ep,ln in allev:
        ch+=ln
        if dd.seen(sig,ep) or sig in routine: continue
        u+=1
        if disp=="runbook": d+=1
    F=ch/4/n; DD=u/n; DE=d/n
    lean=((500*0.1+50*F)/50+20)*DD; neos=DE*(150*0.1+300)+DE*250
    return u,d,lean,neos
print(f"  {'min prevalence':>15s} {'decodes':>8s} {'lean tok/ev':>12s} {'neos tok/ev':>12s} {'saving':>7s}")
print("  "+"-"*60)
for mf in (None,0.0,0.05,0.10,0.20,0.40):
    routine=set() if mf is None else {s for s,ks in prev.items() if len(ks)/len(seed_r)>=mf}
    u,d,l,ne=account(routine)
    lab="laws alone" if mf is None else f"{100*mf:.0f}%"
    print(f"  {lab:>15s} {d:>8,} {l:>12.1f} {ne:>12.1f} {100*(1-ne/l):>6.1f}%")
