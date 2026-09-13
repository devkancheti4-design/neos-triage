"""
THE PACKET -- what flows through neo space.

    words --[encode]--> PACKET --> laws --> PACKET --[decode]--> words

The laws never see words. They read a packet, and a packet has a FIXED
SHAPE. That is the security boundary, not a policy: text arriving in a
message can only ever land in a packet FIELD. There is no path from words to
control, because the only thing that reads words is a transducer that cannot
decide anything, and the only thing that decides reads a schema.

The schema is deliberately format-blind. Nothing in it says "mail". A packet
is a unit of arriving work: does it ask for something, would acting on it
cost something, what values does it carry, how sure is the reading. The same
packet shape would carry a support ticket, a trade confirmation or a log
line, and the laws would rule on it identically.
"""
from dataclasses import dataclass, field, asdict


@dataclass
class Packet:
    # --- what kind of act this unit is, not what it is ABOUT --------------
    asks: bool = False           # requests something of the recipient
    commits: bool = False        # acting on it is expensive or irreversible
    asserts: bool = False        # states fact rather than judgement
    time_bound: bool = False     # turns on a date, a price, availability
    machine: bool = False        # generated rather than written

    # --- what it carries. Keys are named by the ENCODER, never by us ------
    values: dict = field(default_factory=dict)   # {"amount": ["$4,200"], ...}
    topics: list = field(default_factory=list)   # free tags, encoder's words

    # --- how the reading went --------------------------------------------
    confidence: float = 0.0
    language: str = "und"
    summary: str = ""
    degraded: bool = False       # a fallback transducer produced this

    # --- provenance of the unit, measured not read ------------------------
    size: int = 0
    depth: int = 0               # how many turns precede it
    hops: int = 0                # how many times WE have already acted

    def kinds(self):
        """The value-kinds present. This is what hands respond to."""
        return set(self.values)

    def to_dict(self):
        return asdict(self)


# The schema handed to a model encoder. Fixed, closed, and the only thing a
# model is ever allowed to produce.
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asks", "commits", "asserts", "time_bound", "machine",
                 "values", "topics", "confidence", "language", "summary"],
    "properties": {
        "asks":       {"type": "boolean",
                       "description": "requests something of the recipient"},
        "commits":    {"type": "boolean",
                       "description": "acting on it is expensive or irreversible "
                                      "— money, a promise, a booking, a signature, "
                                      "a cancellation, legal exposure"},
        "asserts":    {"type": "boolean",
                       "description": "states a checkable fact rather than a judgement"},
        "time_bound": {"type": "boolean",
                       "description": "turns on a date, time, price or availability"},
        "machine":    {"type": "boolean",
                       "description": "generated rather than written by a person"},
        "values":     {"type": "object", "additionalProperties": {
                           "type": "array", "items": {"type": "string"}},
                       "description": "typed values carried, keyed by a short kind "
                                      "name you choose: amount, reference, deadline, "
                                      "tracking, party, document. Verbatim strings."},
        "topics":     {"type": "array", "items": {"type": "string"},
                       "description": "one to four short tags for what it concerns"},
        "confidence": {"type": "number",
                       "description": "0..1, how sure this reading is"},
        "language":   {"type": "string",
                       "description": "ISO 639-1, or 'und'"},
        "summary":    {"type": "string",
                       "description": "one sentence, what is being asked or said"},
    },
}

REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["body"],
    "properties": {
        "body": {"type": "string",
                 "description": "the reply, in the sender's language, matching "
                                "the register of the prior replies given"},
    },
}
