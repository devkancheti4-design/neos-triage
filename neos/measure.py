"""
MEASUREMENT -- the part route.c leaves undefined, and the part every failure
in this project has turned out to live in.

  "What counts as a shape, a free number, a reader, a chain, a budget or a
   ceiling lives in the MEASUREMENT."                          -- route.c

TWO RULES, both learned the hard way:

  1. PACKET-LOCAL. A unit's bits must be readable from that unit alone.
     Thresholds taken from batch statistics made routing depend on which
     other units happened to be nearby -- 2.7% routed differently
     run to run.

  2. NEVER A HASH. Each bit is a NAMED finding. route()'s partition is
     192/56/7/0/1, so uniform bits into the observation byte return 75.00%
     of units to sender. Measured, not assumed.
"""
import re
from datetime import datetime, timezone

HAZARD_NAMES = ["UNSHAPED", "UNLISTED", "SOLE", "SPENT",
                "NARROW", "BUSY", "CHAINED", "BULK"]
DOUBT_NAMES  = ["UNSURE", "THIN", "FRESH", "CONTESTED",
                "COSTLY", "UNCHECKED", "DRIFTED", "CLAIMED"]

HAZARD_WHY = {
    0: "the message has no parseable ask",
    1: "no hand reads this kind of unit",
    2: "only one hand reads it",
    3: "the account's drafting budget is at its ceiling",
    4: "only two hands read it",
    5: "fewer than three hands are free",
    6: "the agent already spent a hop on this",
    7: "the thread is over the frame ceiling",
}
DOUBT_WHY = {
    0: "the hand reported low confidence",
    1: "it rests on a single message",
    2: "it turns on a date, a time or a price",
    3: "the hands disagreed about what to do",
    4: "the reply commits -- money, a promise, or a booking",
    5: "no second voice checked it",
    6: "the work had not settled",
    7: "it asserts a fact, not a judgement",
}

FRAME_CEILING = 262_144      # bytes; a thread past this is BULK


# ---------------- HAZARDS: read before any draft ------------------------
def hazards(*, parsed_intent: bool, n_read: int, n_free: int,
            agent_hops: int, body_bytes: int,
            budget_used: float, budget_cap: float) -> int:
    """route.c's byte. Every argument is a measurement of ONE mail.

    NOTE on CHAINED. route.c: "arrived over a chain; a hop is already spent."
    That is the AGENT's delegation depth, not the humans' thread depth. Mail
    that is the tenth reply in a conversation has cost the agent nothing --
    it is the first time this agent has seen it. Binding CHAINED to
    References: length routed every threaded mail to ONE, and ONE can service
    almost no check, so 80% of a normal inbox was held for a hop nobody
    spent. Thread depth belongs on the OTHER axis, where a longer thread
    means MORE context and so LESS doubt (see THIN).
    """
    b = 0
    b |= (0 if parsed_intent else 1) << 0            # UNSHAPED
    b |= (1 if n_read == 0 else 0)   << 1            # UNLISTED
    b |= (1 if n_read == 1 else 0)   << 2            # SOLE
    b |= (1 if budget_used >= budget_cap else 0) << 3  # SPENT
    b |= (1 if n_read == 2 else 0)   << 4            # NARROW
    b |= (1 if n_free < 3 else 0)    << 5            # BUSY
    b |= (1 if agent_hops > 0 else 0) << 6           # CHAINED
    b |= (1 if body_bytes >= FRAME_CEILING else 0) << 7  # BULK
    return b


# ---------------- DOUBTS: read off the drafts, before anything leaves ----
_MONEY  = re.compile(r"(?:[$£€]\s?\d|(?:\d[\d,]*\.?\d*)\s?(?:usd|eur|gbp|dollars?|euros?))", re.I)
# what makes a reply expensive or irreversible, read off the INCOMING mail
_ASKS_COMMIT = re.compile(r"\b(?:sign|signature|nda|contract|agreement|terms|"
                          r"invoice|payment|pay|refund|overdue|wire|transfer|"
                          r"purchase|order|deposit|quote|renew)\b", re.I)
# a HARD commitment the draft itself makes -- not "I'll look into it"
_HARD_COMMIT = re.compile(r"\b(?:i (?:agree|approve|accept|confirm)|we (?:agree|approve|accept|confirm)|"
                          r"confirmed|approved|signed|guarantee|i promise|"
                          r"you have my word|consider it done|deal)\b", re.I)
_WHEN   = re.compile(r"\b(?:\d{1,2}[:.]\d{2}\s?(?:am|pm)?|\d{1,2}/\d{1,2}|"
                     r"mon|tue|wed|thu|fri|sat|sun|today|tomorrow|next week|"
                     r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", re.I)
_FACT   = re.compile(r"\b(?:is|are|was|were|has|have|costs?|equals?|totals?)\b\s+"
                     r"(?:\$?\d|the\b|a\b)", re.I)


def _tokens(s): return set(re.findall(r"[a-z0-9']+", s.lower()))


_DECLINE_W = re.compile(r"\b(?:can'?t|cannot|unable|won'?t|decline|not able|"
                        r"afraid not|no longer)\b", re.I)
_ASK_W     = re.compile(r"\b(?:could you|can you|would you|please send|"
                        r"what(?:'s| is)|which|send (?:me|over|the)|"
                        r"let me know)\b", re.I)
_DEFER_W   = re.compile(r"\b(?:i'?ll|we'?ll|come back|follow up|look(?:ing)? into|"
                        r"check(?:ing)?|pull(?:ing)?|revert|"
                        r"read(?:ing)? (?:it )?(?:through|properly))\b", re.I)


def stance(text: str) -> str:
    """What the reply would DO. Disagreement is about action, not phrasing --
    two drafts that both defer in different words are not in conflict, and a
    metric that calls them contested holds mail for no reason."""
    if _HARD_COMMIT.search(text): return "commit"
    if _DECLINE_W.search(text):   return "decline"
    if _ASK_W.search(text):       return "ask"
    if _DEFER_W.search(text):     return "defer"
    return "acknowledge"


def disagreement(drafts) -> float:
    """Fraction of drafters not in the plurality stance. 0 = one mind."""
    if len(drafts) < 2:
        return 0.0
    st = [stance(d) for d in drafts]
    top = max(set(st), key=st.count)
    return 1.0 - st.count(top) / len(st)


def wording_drift(a: str, b: str) -> float:
    """1 - Jaccard. Used only for DRIFTED, where phrasing movement IS the
    signal -- a draft that keeps rewriting itself has not settled."""
    ta, tb = _tokens(a), _tokens(b)
    u = ta | tb
    return 1.0 - (len(ta & tb) / len(u) if u else 1.0)


def doubts(*, drafts, confidences, thread_len: int, voices: int,
           drift: float, incoming: str = "", disagree_at: float = 0.34,
           unsure_at: float = 0.55, drift_at: float = 0.25) -> int:
    """route.c's mirror byte, read off the drafts themselves.

    Every threshold here is an absolute constant chosen once, never a
    quantile of the batch -- a mail's doubt must not depend on what else
    was drafted that hour.
    """
    text = drafts[0] if drafts else ""
    y = 0
    y |= (1 if (min(confidences) if confidences else 0.0) < unsure_at else 0) << 0
    y |= (1 if thread_len <= 1 else 0)                 << 1   # THIN
    y |= (1 if _WHEN.search(incoming) else 0)          << 2   # FRESH
    y |= (1 if disagreement(drafts) > disagree_at else 0) << 3  # CONTESTED
    y |= (1 if (_MONEY.search(incoming) or _ASKS_COMMIT.search(incoming)
                or _HARD_COMMIT.search(text)) else 0) << 4   # COSTLY
    y |= (1 if voices <= 1 else 0)                     << 5   # UNCHECKED
    y |= (1 if drift > drift_at else 0)                << 6   # DRIFTED
    y |= (1 if _FACT.search(text) and not _FACT.search(incoming) else 0) << 7  # CLAIMED
    return y


# Which tier each finding targets. This is the law's wiring, and it is what
# makes a reason nameable: several bits may be set, but only the ones landing
# on the winning tier actually decided the act.
HAZARD_TIER = {0: 0, 1: 0, 2: 1, 3: 1, 6: 1, 4: 2, 5: 2, 7: 2}
DOUBT_TIER  = {0: 1, 2: 1, 7: 1, 1: 2, 5: 2, 6: 2, 3: 4, 4: 4}


def name_bits(byte: int, names, why) -> list:
    return [(names[i], why[i]) for i in range(8) if (byte >> i) & 1]


def deciding_hazards(obs: int, why=None) -> list:
    """The hazards that actually set the act. ROUTE takes the LOWEST tier, so
    a chained unit routes to ONE even when NARROW is also set.

    `why` overrides the wording. The default vocabulary is mail's ("the
    account's drafting budget", "a date, a time or a price"), which is wrong
    in a log tool -- a CA-certificate install was explained to an operator as
    committing "money, a promise, or a booking". The BITS are domain-neutral;
    only the sentences are not."""
    why = why or HAZARD_WHY
    on = [i for i in range(8) if (obs >> i) & 1]
    if not on:
        return []
    win = min(HAZARD_TIER[i] for i in on)
    return [(HAZARD_NAMES[i], why[i]) for i in on if HAZARD_TIER[i] == win]


def deciding_doubts(y: int, why=None) -> list:
    """The doubts that actually set the demand. REDIAL takes the HIGHEST tier.
    `why` overrides the wording -- see deciding_hazards."""
    why = why or DOUBT_WHY
    on = [i for i in range(8) if (y >> i) & 1]
    if not on:
        return []
    win = max(DOUBT_TIER[i] for i in on)
    return [(DOUBT_NAMES[i], why[i]) for i in on if DOUBT_TIER[i] == win]


# ---------------- DOUBTS, read off ACTIONS rather than prose -------------
def doubts_actions(*, actions, case, thread_len: int, voices: int,
                   settled: bool, pkt=None, unsure_at: float = 0.55) -> int:
    """route.c's mirror byte, read off what the hands actually DID.

    Reading doubt off generated prose was a mistake: the drafter's own
    boilerplate set the bits. Actions are typed, so every doubt here is a
    structural fact about the work, not a pattern match on English.
    """
    f = set((case or {}).get("values", {}))
    # CONTESTED compares DISPOSITIONS, not stances. extract, label and
    # calendar have different stances by design -- that is division of
    # labour, not disagreement. Only hands proposing what to DO with the
    # mail can conflict: answer it, close it, or escalate it.
    DISPOSE = {"reply", "archive", "flag"}
    st = {a.kind for a in actions if a.kind in DISPOSE}
    conf = [a.confidence for a in actions] or [0.0]
    reply = next((a for a in actions if a.kind == "reply"), None)
    y = 0
    # UNSURE must hear the PACKET's own confidence, not only the hands'.
    # The transducer is the one thing that read the words: when it says it is
    # unsure -- a one-word message, an instruction embedded in a body, a
    # language it half-read -- that doubt has to reach the laws or it is lost.
    # h03 (an injection attempt) encoded at 0.60 with topic
    # "instruction-in-body" and the laws heard neither.
    pconf = pkt.confidence if pkt else 1.0
    y |= (1 if (min(conf) < unsure_at or pconf < 0.75) else 0)  << 0  # UNSURE
    # THIN and UNCHECKED are doubts about an ANSWER LEAVING. Archiving or
    # flagging sends nothing and is recoverable, so a second voice is not
    # owed. Demanding one held every out-of-office auto-reply for review.
    emits = any(a.kind == "reply" for a in actions)
    y |= (1 if (emits and thread_len <= 1) else 0)              << 1  # THIN
    y |= (1 if (pkt.time_bound if pkt else False) else 0)       << 2  # FRESH
    y |= (1 if len(st) > 1 else 0)                              << 3  # CONTESTED
    y |= (1 if (pkt.commits if pkt else False) else 0)          << 4  # COSTLY
    y |= (1 if (emits and voices <= 1) else 0)                  << 5  # UNCHECKED
    y |= (0 if settled else 1)                                  << 6  # DRIFTED
    y |= (1 if (pkt.asserts if pkt else False) else 0)          << 7  # CLAIMED
    return y
