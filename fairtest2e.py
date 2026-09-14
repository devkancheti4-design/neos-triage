"""Economics with the oracle-seeded boundary applied, whole stream, both sides
on the same safe dedup -- the same accounting as ALERTS.md."""
import sys, pathlib, plistlib, datetime, bisect, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands
from neos.cli import disposition
from fairtest2 import utc, INSTALLERS, LOG, RECEIPTS, WINDOW
SPLIT = datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc).timestamp()
receipts = sorted((r["date"].replace(tzinfo=datetime.timezone.utc).timestamp(),)
                  for r in plistlib.load(open(RECEIPTS,"rb")) if "date" in r)
ad,_ = detect(LOG); hands = default_hands()
allev = []
for ev in read(LOG, ad):
    a,dem,held,obs,d,case,acts = rule(encode(ev), hands=hands)
    allev.append((utc(ev.ts), ev.ident, disposition(case,held,a), signature(ev), ev.epoch, len(ev.message)))
inst = sorted([e for e in allev if e[1] in INSTALLERS and e[0] is not None], key=lambda e:e[0])
times=[e[0] for e in inst]
routine=set()
for (t,) in receipts:
    if t >= SPLIT: continue
    for i in range(bisect.bisect_left(times,t-WINDOW), bisect.bisect_right(times,t+30)):
        if inst[i][2] in ("page","runbook"): routine.add(inst[i][3])

def account(suppress):
    dd = Dedup(window=300); n=len(allev); uniq=0; dec=0; chars=0
    for t,ident,disp,sig,ep,ln in allev:
        chars += ln
        if dd.seen(sig, ep) or (suppress and sig in routine): continue
        uniq += 1
        if disp == "runbook": dec += 1
    FRESH=chars/4/n; DD=uniq/n; DEC=dec/n
    lean=((500*0.1+50*FRESH)/50 + 20)*DD
    neos=DEC*(150*0.1+300) + DEC*250
    return n, uniq, dec, lean, neos

print(f"  {'':34s} {'distinct':>9s} {'decodes':>8s} {'lean tok/ev':>12s} {'neos tok/ev':>12s} {'saving':>7s}")
for label, sup in (("laws alone (ALERTS.md)", False), ("laws + oracle-seeded boundary", True)):
    n,u,d,l,ne = account(sup)
    print(f"  {label:34s} {u:>9,} {d:>8,} {l:>12.1f} {ne:>12.1f} {100*(1-ne/l):>6.1f}%")
print(f"\n  ({n:,} events, whole stream, all processes)")
