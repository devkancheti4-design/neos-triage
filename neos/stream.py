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

# ANSI escapes DEFEAT WORD BOUNDARIES. In "\x1b[31mFAILED" the character
# before F is "m", a word character, so \bfail(ed)? never matches and a red
# FAILED is read as routine. CI output, Docker and Kubernetes colour by
# default, so this silently suppressed errors in exactly the streams people
# most want triaged. Stripped at the boundary, where the rest of the
# vocabulary problem also lives.
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")

LEVELS = {"emerg": 0, "alert": 0, "crit": 0, "fatal": 0, "critical": 0,
          "err": 1, "error": 1, "fail": 1, "warn": 2, "warning": 2,
          "notice": 3, "info": 4, "debug": 5, "trace": 5, "verbose": 5}


_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%a %b %d %H:%M:%S %Y",
    "%b %d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%b/%Y:%H:%M:%S",
)


def parse_ts(ts):
    """Best-effort epoch seconds, or None.

    HONOURS THE OFFSET. The first version stripped "-07" / "+05:30" / "Z"
    and then called .timestamp() on the naive result, which reads it as
    LOCAL time. "2024-10-29 12:54:06-07" became 12:54 in this machine's zone
    instead of 19:54 UTC -- twelve and a half hours out. Windowed dedup did
    not notice, because every event shifted by the same amount. `neos seed`
    noticed immediately: its oracle is in UTC, so every known-good window
    landed on the wrong events and the safety check passed for the wrong
    reason.

    With no offset present the time is still read as local, unchanged:
    BSD syslog carries neither offset nor year and there is no right answer.
    """
    if not ts:
        return None
    import datetime as _dt
    t = re.sub(r"(?<=\d)T(?=\d)", " ", ts.strip())
    t = re.sub(r"([.,]\d+)(?=\s*(?:[-+]\d|Z|$))", "", t)     # fractional seconds
    off = None
    m = re.search(r"(?<=\d)\s*(Z|[-+]\d{2}(?::?\d{2})?)$", t)
    if m:
        z = m.group(1); t = t[:m.start()].rstrip()
        if z == "Z":
            off = 0
        else:
            sign = -1 if z[0] == "-" else 1
            hh, mm = int(z[1:3]), int(z[3:].replace(":", "") or 0)
            off = sign * (hh * 3600 + mm * 60)
    t = re.sub(r"\s+", " ", t).strip()
    for f in _TS_FORMATS:
        try:
            d = _dt.datetime.strptime(t, f)
        except ValueError:
            continue
        if d.year == 1900:                          # syslog-bsd has no year
            d = d.replace(year=_dt.date.today().year)
        if off is None:
            return d.timestamp()                    # naive -> local, as before
        return d.replace(tzinfo=_dt.timezone(_dt.timedelta(seconds=off))).timestamp()
    return None


def strip_ansi(t):
    return ANSI.sub("", t) if t else t


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
                     ident=strip_ansi((g.get("ident") or "").strip()),
                     pid=g.get("pid") or "",
                     level=strip_ansi(g.get("level") or ""),
                     message=strip_ansi(g.get("message") or ""))


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
                     ident=strip_ansi(pick(self.ID)),
                     pid=str(d.get("pid", "") or ""),
                     level=strip_ansi(pick(self.LV)), message=strip_ansi(msg))


class Logfmt(Adapter):
    """`level=error ts=... msg="disk full" svc=api`

    The Grafana/Loki/Prometheus ecosystem emits this and nothing here read
    it, so those streams came back UNREADABLE. Deliberately strict: it needs
    a recognised key, otherwise it would claim any line containing an equals
    sign and parse half the world into nonsense.
    """
    name = "logfmt"
    PAIR = re.compile(r'([A-Za-z_][\w.-]*)=("(?:[^"\\]|\\.)*"|\S*)')
    NEED = {"level", "lvl", "severity", "msg", "message", "time", "ts"}

    def parse(self, line):
        pairs = self.PAIR.findall(line)
        if not pairs:
            return None
        d = {k.lower(): (v[1:-1].replace('\\"', '"') if v[:1] == '"' else v)
             for k, v in pairs}
        if not (self.NEED & set(d)) or len(d) < 2:
            return None
        pick = lambda *ks: next((d[k] for k in ks if d.get(k)), "")
        return Event(ts=pick("ts", "time", "timestamp"),
                     source=pick("host", "hostname"),
                     ident=strip_ansi(pick("logger", "svc", "service", "component", "caller")),
                     pid=pick("pid"),
                     level=strip_ansi(pick("level", "lvl", "severity")),
                     message=strip_ansi(pick("msg", "message", "error", "err")))


class RFC5424(Adapter):
    """`<134>1 2026-09-13T07:45:04Z host app 1 - - message`

    The syslog wire format. The PRI value carries facility*8 + severity, so
    severity is READ here rather than guessed from the words -- which is the
    difference between confidence 1.0 and 0.70 downstream.
    """
    name = "rfc5424"
    RE = re.compile(r"^<(\d{1,3})>1 (\S+) (\S+) (\S+) (\S+) (\S+) (?:\[[^\]]*\]|-)\s?(.*)$")
    SEV = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]

    def parse(self, line):
        m = self.RE.match(line)
        if not m:
            return None
        pri, ts, host, app, procid, _msgid, msg = m.groups()
        return Event(ts="" if ts == "-" else ts, source="" if host == "-" else host,
                     ident=strip_ansi("" if app == "-" else app),
                     pid="" if procid == "-" else procid,
                     level=self.SEV[int(pri) & 7], message=strip_ansi(msg))


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
    RFC5424(),
    Logfmt(),
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
