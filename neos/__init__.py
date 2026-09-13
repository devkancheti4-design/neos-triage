"""
neos -- exact laws for routing work, with no model in the decision.

    route(observation_byte)  -> how many voices open
    redial(doubt_byte)       -> how many must agree
    decline(act, demand)     -> whether the round is refused

Every function is a handful of bit operations over a byte, verified against
a compiled C kernel over all 256 inputs. Nothing is trained, tuned or fitted.

The laws never see words. A transducer converts at each boundary and decides
nothing. Where input already has fields -- events, alerts, telemetry --
that transducer is free, which is where this pays for itself.
"""
from .laws import route, redial, decline, ACT, DEM, HAVE, NEED, KOF, fold_route
from .measure import (hazards, doubts_actions, HAZARD_NAMES, DOUBT_NAMES,
                      deciding_hazards, deciding_doubts)
from .packet import Packet, SCHEMA

__all__ = ["route", "redial", "decline", "ACT", "DEM", "HAVE", "NEED", "KOF",
           "fold_route", "hazards", "doubts_actions", "HAZARD_NAMES",
           "DOUBT_NAMES", "deciding_hazards", "deciding_doubts",
           "Packet", "SCHEMA"]
__version__ = "1.1.0"
