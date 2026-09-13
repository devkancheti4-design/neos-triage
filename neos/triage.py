"""
The round, for a structured stream.

    event --[adapter]--> PACKET --> ROUTE -> hands settle --> REDIAL
          --> DECLINE --> PACKET --> disposition

Identical in shape to the mail agent's Agent.handle(). The laws are imported,
not reimplemented. What differs is the boundary: here it is a regex, so the
encode side of the round costs nothing.
"""
import re, hashlib, collections
from .laws import route, redial, decline, ACT, DEM, HAVE, KOF, fold_route
from .measure import hazards, doubts_actions
from .packet import Packet

NEEDS_ACTION = re.compile(r"\b(error|fail(ed|ure|s)?|denied|refus\w*|timeout|"
                          r"timed out|cannot|can't|unable|invalid|corrupt|"
                          r"missing|abort\w*|fatal|panic|crash\w*|reject\w*|"
                          r"exceeded|exhaust\w*|refused|unauthor\w*)", re.I)
DURABLE = re.compile(r"\b(install\w*|uninstall\w*|remov\w*|delet\w*|writ\w*|"
                     r"mount\w*|unmount\w*|updat\w*|upgrad\w*|migrat\w*|"
                     r"provision\w*|eras\w*|format\w*|reboot\w*|restart\w*|"
                     r"authoriz\w*|entitl\w*|revok\w*|rotat\w*|deploy\w*)", re.I)
DEADLINE = re.compile(r"\b(timeout|timed out|expir\w*|deadline|retry|retries|"
                      r"scheduled|defer\w*|pending|waiting|backoff)", re.I)
NUM = re.compile(r"\d+")
HEXY = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
CODE = re.compile(r"\b(?:error|status|code|result|exit)\s*[:=]?\s*(-?\d+)", re.I)
PATH = re.compile(r"(/(?:[\w.@ -]+/){2,}[\w.@-]*)")


def encode(ev) -> Packet:
    """Event -> packet. Field extraction. No model, no tokens.

    CONFIDENCE IS NOT ALWAYS 1.0, and that matters. When the format carries a
    level field we read it and are certain. When it does not -- syslog has no
    level -- severity is INFERRED from the words, which is exactly the kind of
    guess UNSURE exists to record. ALERTS.md pinned confidence at 1.0 for
    every event and killed the bit; this restores it.
    """
    msg, sev, has_level = ev.message, ev.severity, bool(ev.level)
    v = {}
    c = CODE.search(msg)
    if c: v["code"] = [c.group(1)]
    p = PATH.search(msg)
    if p: v["path"] = [p.group(1)[:120]]
    if ev.pid: v["pid"] = [ev.pid]
    acts = (sev <= 2) if has_level else bool(NEEDS_ACTION.search(msg))
    return Packet(
        asks=acts,
        commits=bool(DURABLE.search(msg)),
        # ASSERTS IS NOT ALWAYS TRUE. alerts.py set it unconditionally and
        # pinned CLAIMED at 100% -- the same defect this project had just
        # published as UNSURE's. A claim means a concrete value, not the
        # bare fact that a line exists.
        asserts=bool(set(v) - {"pid"}),
        time_bound=bool(DEADLINE.search(msg)) or (has_level and sev == 0),
        machine=True,
        values=v, topics=[ev.ident] if ev.ident else [],
        confidence=1.0 if has_level else 0.70,
        language="n/a", summary=msg[:160], degraded=not has_level,
        size=len(msg), depth=1, hops=0)


def signature(ev):
    """What makes two events THE SAME event: identity plus the message with
    its varying parts erased. This is the dedup and it is a hash set, not a
    law -- ALERTS.md gives it no credit and neither does this."""
    n = UUID.sub("#", HEXY.sub("#", NUM.sub("#", ev.message)))[:180]
    return hashlib.blake2b(f"{ev.ident}|{n}".encode(), digest_size=16).digest()


class Dedup:
    """Bounded, and it RE-ALERTS.

    The first version suppressed every repeat after the first, and measuring
    it against independent ground truth (fsck exit codes in a separate file)
    gave **0% incident recall**: the line `error: container /dev/rdisk1 is
    mounted with write access` recurs 1,113 times, dedup saw it once, and
    every subsequent failed fsck run was invisible. A recurring error is
    still an error every time it recurs.

    Now a signature surfaces on occurrence 1, 2, 4, 8, 16 ... -- log-scale
    re-alerting, the same shape as an alert manager's repeat interval. For
    1,113 repeats that is 11 surfacings instead of 1: still a 99% reduction,
    but the incident is never invisible.

    An unbounded dict over a live stream is an OOM with a delay on it, so it
    stays capped.
    """
    def __init__(self, cap=200_000, realert=True, window=300.0, every=20):
        self.cap, self.realert = cap, realert
        self.window, self.every = window, every
        self.d = collections.OrderedDict()

    def seen(self, sig, epoch=None):
        """True = this occurrence should be HIDDEN as a repeat.

        WINDOWED when the stream carries a timestamp. The same signature
        legitimately recurs across INDEPENDENT incidents -- 59 separate fsck
        runs each emit a byte-identical `error: container ... is mounted with
        write access`. Global-forever dedup cannot tell them apart and gave
        0% incident recall against independent exit-code ground truth.
        Bucketing by time can: two failures five minutes apart are two.

        When there is no usable timestamp it falls back to surfacing every
        `every`-th occurrence, which bounds how many can hide in a row. It
        does NOT fall back to exponential backoff: by occurrence 900 the next
        surfacing would be 1024, and 124 consecutive incidents would be
        invisible.
        """
        if self.realert and self.window and epoch is not None:
            sig = (sig, int(epoch // self.window))
        n = self.d.get(sig, 0) + 1
        self.d[sig] = n
        self.d.move_to_end(sig)
        if len(self.d) > self.cap:
            self.d.popitem(last=False)
        if n == 1:
            return False
        if not self.realert:
            return True
        if self.window and epoch is not None:
            return True                    # already surfaced in this window
        return n % self.every != 0
    def __len__(self): return len(self.d)
    def loudest(self, k=5):
        return sorted(self.d.items(), key=lambda t: -t[1])[:k]


# ------------------------------------------------------------- the hands
class Hand:
    name, kind, disposes = "hand", "none", False
    def reads(self, pkt, case): return False, 0.0
    def work(self, pkt, case): raise NotImplementedError


class Act:
    __slots__ = ("hand", "kind", "payload", "confidence", "stance")
    def __init__(self, hand, kind, payload, confidence, stance):
        self.hand, self.kind, self.payload = hand, kind, payload
        self.confidence, self.stance = confidence, stance


class Correlate(Hand):
    name, kind = "correlate", "values"
    def reads(self, pkt, case): return bool(pkt.values), 0.8
    def work(self, pkt, case): return Act(self.name, "values", dict(pkt.values), 0.8, "observe")

class Classify(Hand):
    name, kind = "classify", "label"
    def reads(self, pkt, case): return bool(pkt.topics or pkt.values), 0.85
    def work(self, pkt, case):
        return Act(self.name, "label",
                   {"labels": sorted(set(pkt.topics) | set(pkt.values))}, 0.85, "observe")

class Bucket(Hand):
    name, kind = "bucket", "file"
    def reads(self, pkt, case): return bool(case.get("labels")), 0.7
    def work(self, pkt, case):
        return Act(self.name, "file", {"folder": (case.get("labels") or ["unsorted"])[0]},
                   0.7, "observe")

class Runbook(Hand):
    """The ONLY hand that ever needs words written, and therefore the only
    place a decode token is ever spent."""
    name, kind, disposes = "runbook", "reply", True
    def reads(self, pkt, case): return (pkt.asks and pkt.commits), 0.75
    def work(self, pkt, case):
        return Act(self.name, "reply", {"skeleton": pkt.summary, "from_case": "runbook"},
                   0.75, "act")

class Page(Hand):
    name, kind, disposes = "page", "flag", True
    def reads(self, pkt, case): return (pkt.asks and pkt.time_bound), 0.8
    def work(self, pkt, case):
        return Act(self.name, "flag", {"why": "actionable and time-bound"}, 0.8, "escalate")

class Ticket(Hand):
    """An actionable event that is neither urgent nor state-changing. That is
    a bug report, not an incident: queue it, do not wake anyone.

    THIS HAND EXISTS BECAUSE OF A HOLE. An exhaustive sweep of all 64 packet
    shapes found 6 -- every one with asks=1, commits=0, time_bound=0 -- that
    the laws ruled on and then NO hand disposed of. Runbook wants asks AND
    commits; Page wants asks AND time_bound; Suppress only reads NOT asks.
    The gap between them was silent: 837 of 847 events in one real stream
    came out ruled and went nowhere. tests/test_triage.py now proves the
    hand set is total, the same way the laws are proved total."""
    name, kind, disposes = "ticket", "link", True
    def reads(self, pkt, case):
        return (pkt.asks and not (pkt.commits or pkt.time_bound)), 0.65
    def work(self, pkt, case):
        return Act(self.name, "link", {"queue": "triage"}, 0.65, "queue")


class Suppress(Hand):
    name, kind, disposes = "suppress", "archive", True
    def reads(self, pkt, case): return (not pkt.asks), 0.9
    def work(self, pkt, case): return Act(self.name, "archive", {}, 0.9, "close")


def default_hands():
    return [Correlate(), Classify(), Bucket(), Runbook(), Page(),
            Ticket(), Suppress()]

DISPOSE = {True: ("runbook", "page", "ticket"), False: ("suppress",)}


def _settled_mark(case):
    """A cheap fingerprint of everything the settle loop can mutate.

    This was `json.dumps(case, sort_keys=True, default=str)`, called twice
    per round -- 8 serialisations per event. Profiling put it at 39% of
    total runtime while route(), the actual law, was 2.4%. The laws were
    never the cost; asking "did anything change?" was.

    Every key below is one a hand writes in the loop. If a hand starts
    writing a new key, add it here -- test_settle_mark_covers_every_key
    fails if you forget.
    """
    f = case.get("flags")
    return (tuple(case.get("labels") or ()), case.get("folder"),
            repr(case.get("plan")), len(f) if f else 0,
            case.get("archive"), repr(case.get("ticket")))


def rule(pkt, hands=None, budget_used=0.0, budget_cap=1e9, rounds=4):
    """One round. Returns (act, demand, held, obs, doubt, case, actions)."""
    hands = hands or default_hands()
    case = {"dispose": DISPOSE[bool(pkt.asks)]}
    acts_seen, settled, actions = [], False, []
    for r in range(rounds):
        reads = [(h, c) for h in hands for ok, c in [h.reads(pkt, case)] if ok]
        reads.sort(key=lambda t: -t[1])
        # `or pkt.summary` WAS DROPPED when this round was ported from
        # the reference implementation these laws were first written for, and the divergence was silent: an event that
        # parsed perfectly but carried no extractable values read as UNSHAPED
        # and the law declined to open a round at all. 837 of 847 distinct
        # events in one real stream came out "no-call" -- the laws never
        # engaged, and the rate was really a measure of how much the ADAPTER
        # bothered to extract. A message IS something to read.
        obs = hazards(parsed_intent=bool(reads) and bool(pkt.asks or pkt.values
                                                         or pkt.summary),
                      n_read=len(reads), n_free=max(1, len(hands) - 1),
                      agent_hops=pkt.hops, body_bytes=pkt.size,
                      budget_used=budget_used, budget_cap=budget_cap)
        act = route(obs)
        acts_seen.append(act)
        if act == 0:
            return 0, 0, False, obs, 0, case, []
        chosen = reads[:min(KOF[act], len(reads))]
        actions = [h.work(pkt, case) for h, _ in chosen]
        before = _settled_mark(case)
        for a in actions:
            if a.kind == "label":     case["labels"] = a.payload["labels"]
            elif a.kind == "file":    case["folder"] = a.payload["folder"]
            elif a.kind == "reply":   case["plan"] = a.payload
            elif a.kind == "flag":    case.setdefault("flags", []).append(a.payload)
            elif a.kind == "link":    case["ticket"] = a.payload
            elif a.kind == "archive": case["archive"] = True
        budget_used += len(chosen)
        if _settled_mark(case) == before:
            settled = True
            break
    a = fold_route(acts_seen)
    d = doubts_actions(actions=actions, case=case, thread_len=1,
                       voices=HAVE[a], settled=settled, pkt=pkt)
    dem = redial(d)
    return a, dem, bool(decline(a, dem)), obs, d, case, actions


# The same eight bits, said in the operator's language instead of the
# mailroom's. The BITS do not change -- only the sentence attached to one.
HAZARD_WHY = {
    0: "the event carries nothing readable",
    1: "no hand handles this kind of event",
    2: "only one hand handles it",
    3: "the run's hand budget is at its ceiling",
    4: "only two hands handle it",
    5: "fewer than three hands are free",
    6: "this event has already been acted on once",
    7: "the event exceeds the size ceiling",
}
DOUBT_WHY = {
    0: "severity was inferred from the text, not read from a level field",
    1: "it rests on a single occurrence",
    2: "it turns on a timeout, a retry or a deadline",
    3: "the hands propose different dispositions",
    4: "it changes durable state -- an install, a write, a revocation",
    5: "no second hand corroborated it",
    6: "the case was still changing when the round ended",
    7: "it reports a concrete value -- a code, a status or a path",
}
