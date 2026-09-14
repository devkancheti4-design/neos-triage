import re, sys, pathlib, collections, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from neos.stream import Event
from neos.triage import encode, signature, Dedup, rule, default_hands
from neos.cli import disposition
from neos.label import wilson

ERRLOG, MAINLOG = "/var/log/fsck_apfs_error.log", "/var/log/fsck_apfs.log"
SURFACED = {"page", "runbook", "ticket", "held"}

# ---------- ORACLE: (completion time, container) -> exit code. Separate file.
res = re.compile(r"dev=(\S*)\s+.*?result=(\d+)")
done = re.compile(r"fsck_apfs completed at (.+)$")
oracle, pending = {}, []
for line in open(ERRLOG, errors="replace"):
    m = res.search(line)
    if m:
        pending.append((m.group(1), int(m.group(2)))); continue
    d = done.search(line.strip())
    if d and pending:
        ts = d.group(1).strip()
        for dev, r in pending:
            if dev:                                  # container-level entries only
                k = (ts, dev)
                oracle[k] = max(oracle.get(k, 0), r)
        pending = []
print(f"  ORACLE (fsck_apfs_error.log, exit codes, never seen by the tool)")
print(f"    {len(oracle)} (time, container) runs: "
      f"{sum(1 for v in oracle.values() if v)} non-zero, "
      f"{sum(1 for v in oracle.values() if not v)} clean\n")
if not oracle:
    # REFUSE, do not report. On 2026-09-14 macOS truncated the error log to
    # zero bytes and this harness printed "INCIDENT RECALL 0.0% [0.0%, 0.0%]"
    # -- a 0/0 dressed as a measurement. An oracle that has vanished is a
    # different fact from a tool that catches nothing, and the two must
    # never print the same line.
    raise SystemExit("  ORACLE IS EMPTY. The ground truth file was truncated or rotated.\n"
                     "  Nothing can be measured. Point ORACLE at a snapshot, or re-run\n"
                     "  fsck to regenerate exit codes. No number is reported.")

# ---------- THE TOOL on the human-readable log
LINE = re.compile(r"^(/dev/\S+?):\s?(.*)$")
STARTED = re.compile(r"fsck_apfs started at (.+)$")
COMPLETED = re.compile(r"fsck_apfs completed at (.+)$")

def run_tool(ablate=False, dedup=True):
    """Group lines into runs per partition; ask what the tool did with each."""
    hands, dd = default_hands(), Dedup()
    cur_ts = {}
    open_runs = collections.defaultdict(list)      # partition -> [dispositions]
    finished = []                                  # (ts, container, [dispositions])
    for raw in open(MAINLOG, errors="replace"):
        m = LINE.match(raw.rstrip("\n"))
        if not m:
            continue
        part, msg = m.group(1), m.group(2)
        if ablate:
            # THE ABLATION: remove the one word the tool's pattern keys on.
            # Everything else about the line is untouched; the run is still
            # a failure and still says the container is mounted with write
            # access. Only the giveaway is gone.
            msg = re.sub(r"\berror\b:?\s*", "", msg, flags=re.I)
        cont = re.sub(r"s\d+$", "", part)
        st = STARTED.search(msg)
        if st:
            open_runs[part] = []
            cur_ts[part] = st.group(1).strip()
        ev = Event(ident=part, level="", ts=cur_ts.get(part, ""), message=msg)
        a, dem, held, obs, d, case, acts = rule(encode(ev), hands=hands)
        disp = disposition(case, held, a)
        if dedup and dd.seen(signature(ev), ev.epoch):
            disp = "deduped"
        open_runs[part].append(disp)
        c = COMPLETED.search(msg)
        if c:
            finished.append((c.group(1).strip(), cont, open_runs.pop(part, [])))
    return finished

def scoreboard(finished, title):
    caught = missed = fp = tn = unmatched = 0
    misses = []
    caught_d = []
    for ts, cont, disps in finished:
        key = (ts, cont)
        if key not in oracle:
            unmatched += 1; continue
        surfaced = any(d in SURFACED for d in disps)
        if oracle[key]:
            if surfaced: caught += 1; caught_d.append((ts, cont, disps))
            else: missed += 1; misses.append((ts, cont, disps))
        else:
            if surfaced: fp += 1
            else: tn += 1
    tot = caught + missed
    p, lo, hi = wilson(caught, tot) if tot else (0, 0, 0)
    fpp, flo, fhi = wilson(fp, fp + tn) if (fp + tn) else (0, 0, 0)
    print(f"  {title}")
    print(f"    incidents  {tot:>4}   caught {caught:>4}   MISSED {missed:>4}")
    print(f"    clean runs {fp+tn:>4}   false-paged {fp:>4}")
    print(f"    INCIDENT RECALL      {100*p:5.1f}%   95% CI "
          f"[{100*lo:.1f}%, {100*hi:.1f}%]")
    print(f"    false page rate      {100*fpp:5.1f}%   95% CI "
          f"[{100*flo:.1f}%, {100*fhi:.1f}%]")
    if unmatched:
        print(f"    ({unmatched} runs had no oracle entry and were excluded)")
    agg = collections.Counter()
    for ts, cont, disps in caught_d:
        for d in disps:
            if d in SURFACED: agg[d] += 1
    if agg: print(f"    HOW the caught ones surfaced: {dict(agg)}")
    print()
    return p

a = scoreboard(run_tool(False), "AS SHIPPED NOW -- rule first, dedup re-alerts")
d = scoreboard(run_tool(True), "ABLATED -- the word 'error' removed from every line")
print(f"  as shipped now        {100*a:5.1f}%")
print(f"  with 'error' ablated  {100*d:5.1f}%   <- the laws on structure alone")
