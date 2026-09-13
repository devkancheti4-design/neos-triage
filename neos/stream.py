"""
Adapters. An event arrives already structured; this finds the fields.

THIS IS THE WHOLE ENCODER for a structured stream, and it costs zero tokens.
That is the entire economic argument (ALERTS.md): the architecture converts
decision cost into encoding cost, so it wins wherever encoding is cheaper
than deciding. Here encoding is a regex.

Adapters are tried against a sample of the real file and the best match wins,
because guessing a format from its name is how you end up parsing 0% of a
stream and reporting a 100% suppression rate.
"""
import re, json
from dataclasses import dataclass

LEVELS = {"emerg": 0, "alert": 0, "crit": 0, "fatal": 0, "critical": 0,
          "err": 1, "error": 1, "fail": 1, "warn": 2, "warning": 2,
          "notice": 3, "info": 4, "debug": 5, "trace": 5, "verbose": 5}


_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%a %b %d %H:%M:%S %Y",
    "%b %d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%b/%Y:%H:%M:%S",
)


def parse_ts(ts):
    """Best-effort epoch seconds, or None. Tolerant on purpose: dedup falls
    back to counting when a stream carries no usable time, and a wrong
    timestamp is worse than none."""
    if not ts:
        return None
    import datetime as _dt
    # NOT a bare .replace("T", " "): that turns "Thu Sep 10" into "hu Sep 10"
    # and silently returns None for every BSD-style timestamp. The ISO
    # separator only counts between a digit and a digit.
    t = re.sub(r"(?<=\d)T(?=\d)", " ", ts.strip())
    t = re.sub(r"(?<=\d)Z$", "", t)
    t = re.sub(r"([.,]\d+)", "", t)                 # drop fractional seconds
    t = re.sub(r"\s*[-+]\d{2}:?\d{0,2}$", "", t)    # drop trailing offset
    t = re.sub(r"\s+", " ", t).strip()
    for f in _TS_FORMATS:
        try:
            d = _dt.datetime.strptime(t, f)
            if d.year == 1900:                      # syslog-bsd has no year
                d = d.replace(year=_dt.date.today().year)
            return d.timestamp()
        except ValueError:
            continue
    return None


@dataclass
class Event:
    ts: str = ""
    source: str = ""          # host / service
    ident: str = ""           # process / component / logger
    pid: str = ""
    level: str = ""           # as written, or "" when the format has none
    message: str = ""

    @property
    def epoch(self):
        return parse_ts(self.ts)

    @property
    def severity(self):
        """0 worst .. 5 noise. 3 when the format carries no level at all."""
        return LEVELS.get(self.level.strip().lower(), 3)


class Adapter:
    name = "adapter"
    def parse(self, line): raise NotImplementedError


class Regex(Adapter):
    def __init__(self, name, pattern, fields):
        self.name, self.re, self.fields = name, re.compile(pattern), fields
    def parse(self, line):
        m = self.re.match(line)
        if not m:
            return None
        g = dict(zip(self.fields, m.groups()))
        return Event(ts=g.get("ts", "") or "", source=(g.get("source") or "").strip(),
                     ident=(g.get("ident") or "").strip(), pid=g.get("pid") or "",
                     level=g.get("level") or "", message=g.get("message") or "")


class NDJSON(Adapter):
    """JSON per line. Field names vary by vendor, so several spellings of the
    same thing are accepted -- this is the format most enterprise telemetry
    actually arrives in."""
    name = "ndjson"
    TS = ("timestamp", "ts", "time", "@timestamp", "eventTime", "date")
    LV = ("level", "severity", "levelname", "lvl", "log.level", "eventType")
    ID = ("logger", "component", "service", "source", "name", "eventType",
          "subsystem", "process")
    MSG = ("message", "msg", "text", "event", "body", "commandLine")

    def parse(self, line):
        line = line.strip()
        if not line.startswith("{"):
            return None
        try:
            d = json.loads(line)
        except Exception:
            return None
        if not isinstance(d, dict):
            return None
        pick = lambda ks: next((str(d[k]) for k in ks if d.get(k) not in (None, "")), "")
        msg = pick(self.MSG)
        if not msg:                      # no obvious message: serialise the rest
            msg = " ".join(f"{k}={v}" for k, v in sorted(d.items())
                           if k not in self.TS + self.LV)[:500]
        return Event(ts=pick(self.TS), source=str(d.get("host", "") or ""),
                     ident=pick(self.ID), pid=str(d.get("pid", "") or ""),
                     level=pick(self.LV), message=msg)


ADAPTERS = [
    # 2024-10-29 12:54:06-07 host proc[53]: message
    Regex("syslog-iso",
          r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[-+]\d{2}(?::?\d{2})?|Z)?)"
          r"\s+(\S+)\s+([^\[\s][^\[]*)\[(\d+)\]:\s?(.*)$",
          ("ts", "source", "ident", "pid", "message")),
    # Sep 13 00:01:10 host proc[363]: message
    Regex("syslog-bsd",
          r"^([A-Z][a-z]{2}\s+\d{1,2} \d{2}:\d{2}:\d{2})\s+(\S+)\s+"
          r"([^\[\s][^\[]*)\[(\d+)\]:\s?(.*)$",
          ("ts", "source", "ident", "pid", "message")),
    # 2026-01-30 09:39:22.465 - [ 4120] - [ 1] - INFO - [Component] message
    Regex("dotnet",
          r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+) - \[\s*(\d+)\] - "
          r"\[\s*\d+\] - (\w+)\s+- \[([^\]]+)\]\s?(.*)$",
          ("ts", "pid", "level", "ident", "message")),
    # [VM] 2026-03-23 18:58:36 [info] message
    Regex("tagged",
          r"^\[([^\]]+)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\]\s?(.*)$",
          ("ident", "ts", "level", "message")),
    NDJSON(),
]


def detect(path, sample=4000):
    """Try every adapter on a real sample and take the best match rate.

    Returns (adapter, rate). A rate below ~0.5 means the stream is not one
    this tool can read, and the caller is told rather than handed a
    confident-looking 0%-parsed result."""
    counts = {a.name: 0 for a in ADAPTERS}
    n = 0
    with open(path, "r", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            for a in ADAPTERS:
                if a.parse(line.rstrip("\n")):
                    counts[a.name] += 1
            if n >= sample:
                break
    if not n:
        return None, 0.0
    best = max(ADAPTERS, key=lambda a: counts[a.name])
    return best, counts[best.name] / n


def read(path, adapter=None):
    """Yield Events. Lines the adapter cannot parse are folded into the
    previous event as continuation text (stack traces, plist dumps) rather
    than dropped -- dropping them silently inflates every rate downstream."""
    ad = adapter or detect(path)[0]
    if ad is None:
        return
    prev = None
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            e = ad.parse(line)
            if e is None:
                if prev is not None and len(prev.message) < 4000:
                    prev.message += " " + line.strip()
                continue
            if prev is not None:
                yield prev
            prev = e
    if prev is not None:
        yield prev
