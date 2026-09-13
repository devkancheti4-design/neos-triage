"""
Tests for the deployable core. The point of these is not that the code runs;
it is that the two properties a deployment depends on are PROVED, not sampled:

  1. the hand set is TOTAL   -- no packet shape is ruled and then dropped
  2. memory is BOUNDED       -- a live stream cannot grow the dedup forever
"""
import itertools, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neos.packet import Packet
from neos.triage import rule, Dedup, encode, signature, default_hands
from neos.stream import Event, ADAPTERS, NDJSON, detect

CASES = []
def case(fn):
    CASES.append(fn); return fn


def shape(asks, commits, tb, has_v, has_t, lvl):
    v = {"code": ["1"], "pid": ["9"]} if has_v else {}
    return Packet(asks=bool(asks), commits=bool(commits), asserts=bool(has_v),
                  time_bound=bool(tb), machine=True, values=v,
                  topics=["x"] if has_t else [], confidence=1.0 if lvl else 0.70,
                  language="n/a", summary="s", degraded=not lvl,
                  size=80, depth=1, hops=0)


@case
def test_the_hand_set_is_total_over_every_packet_shape():
    """6 of 64 shapes once fell through: asks and not (commits or time_bound)
    was read by no disposing hand at all, and 837 real events went nowhere."""
    holes = []
    for bits in itertools.product([0, 1], repeat=6):
        a, dem, held, obs, d, cs, acts = rule(shape(*bits))
        if a != 0 and not held and not any(
                cs.get(f) for f in ("plan", "flags", "ticket", "archive")):
            holes.append(bits)
    assert not holes, f"{len(holes)} shapes ruled and disposed of by nothing: {holes}"


@case
def test_every_ruled_packet_gets_exactly_one_terminal_disposition():
    """Belt and braces: not just 'something happened' but that a disposing
    hand ran. A label is not a disposition."""
    for bits in itertools.product([0, 1], repeat=6):
        a, dem, held, obs, d, cs, acts = rule(shape(*bits))
        if a == 0 or held:
            continue
        assert any(x.kind in ("reply", "flag", "link", "archive") for x in acts), bits


@case
def test_dedup_memory_is_bounded():
    d = Dedup(cap=100)
    for i in range(10_000):
        d.seen(f"sig{i}".encode())
    assert len(d) <= 100, len(d)


@case
def test_dedup_realerts_so_a_recurring_incident_is_never_invisible():
    """Suppressing every repeat gave 0% INCIDENT RECALL against independent
    ground truth: `error: container /dev/rdisk1 is mounted with write access`
    recurs 1,113 times in fsck_apfs.log, dedup saw it once, and every later
    failed fsck run was invisible. A recurring error is still an error."""
    # No timestamp -> every 20th. Bounded: at most 19 can hide in a row.
    # NOT exponential backoff, which was the first fix and was still wrong:
    # by occurrence 900 the next surfacing is 1024, so 124 consecutive
    # incidents would be invisible.
    d = Dedup(cap=4000)
    surfaced = [i for i in range(1, 1114) if not d.seen(b"same")]
    assert surfaced[:4] == [1, 20, 40, 60], surfaced[:4]
    assert max(b - a for a, b in zip(surfaced, surfaced[1:])) <= 20
    assert 50 < len(surfaced) < 60, len(surfaced)

    # With a timestamp -> one per window, so two INDEPENDENT incidents five
    # minutes apart are two incidents, not one repeat. This is the property
    # that took recall from 0% to 71.2% against independent ground truth.
    w = Dedup(cap=4000, window=300.0)
    t0 = 1_700_000_000.0
    assert not w.seen(b"x", t0)                 # first in window: surfaces
    assert w.seen(b"x", t0 + 10)                # same window: repeat
    assert not w.seen(b"x", t0 + 600)           # new window: surfaces again


@case
def test_dedup_with_realert_off_is_the_old_behaviour():
    d = Dedup(cap=1000, realert=False)
    assert [i for i in range(1, 50) if not d.seen(b"x")] == [1]


@case
def test_the_laws_run_before_dedup_not_after():
    """The laws cost zero tokens, so a hash set in front of them buys nothing
    and costs incidents. Dedup gates the EXPENSIVE step, not the free one."""
    import inspect
    from neos.cli import verdicts
    src = inspect.getsource(verdicts)
    i_rule, i_dedup = src.index("rule("), src.index("dd.seen(")
    assert i_rule < i_dedup, "dedup runs before the laws again"


@case
def test_dedup_counts_repeats_and_keeps_the_loud_ones_hot():
    d = Dedup(cap=10)
    for _ in range(50):
        d.seen(b"noisy")
    for i in range(9):
        d.seen(f"q{i}".encode())
    assert d.seen(b"noisy"), "the loudest signature was evicted"


@case
def test_confidence_is_not_pinned_when_the_format_has_no_level():
    """alerts.py set confidence=1.0 on every event and killed UNSURE. A
    format without a level field means severity was INFERRED."""
    withlvl = encode(Event(ident="a", level="ERROR", message="disk failed"))
    nolvl = encode(Event(ident="a", level="", message="disk failed"))
    assert withlvl.confidence == 1.0 and nolvl.confidence < 0.75
    assert nolvl.degraded and not withlvl.degraded


@case
def test_asserts_is_not_always_true():
    """alerts.py set asserts=True unconditionally and pinned CLAIMED at 100%
    -- the identical defect this project had published as UNSURE's."""
    bare = encode(Event(ident="a", message="started"))
    withval = encode(Event(ident="a", message="failed with error: 42"))
    assert not bare.asserts and withval.asserts


@case
def test_signature_collapses_varying_ids_but_not_different_events():
    e = lambda m: Event(ident="p", message=m)
    assert signature(e("retry 41 of 99")) == signature(e("retry 7 of 99"))
    assert signature(e("disk full")) != signature(e("disk ok"))
    assert signature(Event(ident="a", message="x")) != \
           signature(Event(ident="b", message="x"))


@case
def test_every_adapter_parses_its_own_format():
    samples = {
        "logfmt": 'level=error ts=2026-09-13T07:45:04Z msg="disk full" svc=api',
        "rfc5424": "<131>1 2026-09-13T07:45:04Z host app 1 - - failed to authenticate",
        "syslog-iso": "2024-10-29 12:54:06-07 host softwareupdated[176]: Starting",
        "syslog-bsd": "Sep 13 00:01:10 host syslogd[363]: ASL Sender Statistics",
        "dotnet": "2026-01-30 09:39:22.465 - [  4120] - [     1] - INFO  - "
                  "[Unity.Licensing.Client.Program] Command line arguments",
        "tagged": "[VM] 2026-03-23 18:58:36 [info] startVM called",
        "ndjson": '{"level":"ERROR","logger":"svc","message":"boom"}',
    }
    by = {a.name: a for a in ADAPTERS}
    for name, line in samples.items():
        ev = by[name].parse(line)
        assert ev is not None, f"{name} failed to parse its own sample"
        assert ev.message, f"{name} parsed but produced no message"


@case
def test_adapters_do_not_claim_formats_that_are_not_theirs():
    """Detection picks the best match rate. An adapter that matches anything
    would win every stream and parse all of it into nonsense."""
    by = {a.name: a for a in ADAPTERS}
    assert by["ndjson"].parse("Sep 13 00:01:10 host p[1]: x") is None
    assert by["syslog-bsd"].parse('{"level":"ERROR"}') is None
    assert by["dotnet"].parse("Sep 13 00:01:10 host p[1]: x") is None


@case
def test_severity_maps_and_defaults_to_the_middle():
    assert Event(level="ERROR").severity == 1
    assert Event(level="debug").severity == 5
    assert Event(level="").severity == 3, "no level must not read as critical"


@case
def test_the_laws_are_imported_not_reimplemented():
    """The whole claim rests on these being the same laws. If triage.py ever
    grows its own copy, this fails."""
    import neos.triage as t, neos.laws as l, inspect
    src = inspect.getsource(t)
    assert "def route(" not in src and "def redial(" not in src \
        and "def decline(" not in src, "triage.py reimplemented a law"
    assert t.route is l.route and t.redial is l.redial and t.decline is l.decline




@case
def test_the_round_matches_the_reference_round_in_mailagent():
    """Skipped here: it pins this round against the sibling implementation
    the laws were first written for, which is not distributed in this
    repository. Kept because `or pkt.summary` was dropped in that port and
    837 real events silently became no-calls -- see DEPLOY.md."""
    import inspect, re as _re
    import neos.triage as t
    try:
        import mailagent.agent as ag
    except Exception:
        return                                  # mail agent optional
    grab = lambda src: set(_re.search(
        r"parsed_intent=bool\(reads\) and bool\((.*?)\),", src, _re.S).group(1).split("or"))
    norm = lambda s: {x.strip().replace("\n", " ").split()[-1] for x in s}
    assert norm(grab(inspect.getsource(t))) == norm(grab(inspect.getsource(ag))), \
        "triage round diverged from the reference round"


@case
def test_a_readable_message_with_no_values_still_opens_a_round():
    from neos.stream import Event
    p = encode(Event(ident="VM", level="info", message="VM startup step: stop_existing_vm started"))
    a, dem, held, obs, d, cs, acts = rule(p)
    assert a != 0, "an event that parsed fine was ruled unreadable"
    assert cs.get("archive"), "informational event was not suppressed"


@case
def test_the_decision_path_has_no_dependencies_and_no_network():
    """pyproject declares zero dependencies. This proves it, and proves the
    decision path cannot reach a network or a model -- the property the whole
    architecture rests on."""
    import ast, pathlib as _p
    banned = {"requests", "httpx", "urllib", "urllib3", "socket", "http",
              "anthropic", "openai", "torch", "numpy", "aiohttp", "ssl"}
    root = _p.Path(__file__).resolve().parent.parent / "neos"
    for f in sorted(root.glob("*.py")):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [(node.module or "").split(".")[0]]
            bad = set(mods) & banned
            assert not bad, f"{f.name} imports {bad}"


@case
def test_no_send_no_write_no_execute_anywhere_in_the_core():
    """A triage tool that can act on its own conclusions is an outage
    generator. This one reports; a human or a downstream system acts."""
    import pathlib as _p
    root = _p.Path(__file__).resolve().parent.parent / "neos"
    for f in sorted(root.glob("*.py")):
        src = f.read_text()
        for bad in ("subprocess", "os.system", "os.remove", "shutil.rmtree",
                    "os.kill", "eval(", "exec("):
            assert bad not in src, f"{f.name} contains {bad}"





@case
def test_the_event_total_counts_trailing_duplicates():
    """Reading the total off the last yielded verdict undercounts by however
    many duplicate events trail the final distinct one -- 914 of 215,089 on
    a real file, silently."""
    import tempfile, os as _os
    from neos.cli import verdicts
    from neos.stream import ADAPTERS
    from neos.triage import default_hands
    by = {a.name: a for a in ADAPTERS}
    line = "2024-10-29 12:54:0%d-07 h p[1]: %s\n"
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write(line % (0, "unique alpha"))
        for i in range(20):                 # 20 duplicates AFTER the last new one
            f.write(line % (1, "same same"))
        path = f.name
    try:
        stats = {}
        rows = list(verdicts(path, by["syslog-iso"], default_hands(), 1e9, 1000, stats))
        assert stats["events"] == 21, stats["events"]
        # All 20 duplicates share one timestamp second, so they fall in one
        # window and surface once: 1 unique + 1 = 2.
        assert len(rows) == 2, len(rows)
    finally:
        _os.unlink(path)


@case
def test_wilson_never_claims_certainty_from_a_small_clean_sample():
    """0 failures in 40 is NOT a 0% failure rate. The normal approximation
    returns [0,0] here and would let this report perfect safety."""
    from neos.label import wilson
    p, lo, hi = wilson(0, 40)
    assert p == 0.0 and lo == 0.0
    assert 0.05 < hi < 0.12, hi
    _, _, hi400 = wilson(0, 400)
    assert hi400 < hi, "more evidence must tighten the bound"


@case
def test_sampling_is_stratified_so_rare_classes_are_measured():
    """A uniform sample of install.log would be ~97% suppressions and would
    measure the paging decision not at all."""
    from neos.label import draw
    rows = ([{"disposition": "suppress", "message": f"s{i}"} for i in range(8000)]
            + [{"disposition": "page", "message": f"p{i}"} for i in range(3)])
    sample, strata = draw(rows, per_stratum=40, seed=1)
    got = {}
    for r in sample:
        got[r["disposition"]] = got.get(r["disposition"], 0) + 1
    assert got["page"] == 3, got
    assert got["suppress"] == 40, got
    assert strata == {"suppress": 8000, "page": 3}
    assert all(r["human"] == "" for r in sample)


@case
def test_draw_is_reproducible_for_a_seed():
    from neos.label import draw
    rows = [{"disposition": "suppress", "message": f"s{i}"} for i in range(500)]
    a, _ = draw(rows, per_stratum=20, seed=3)
    b, _ = draw(rows, per_stratum=20, seed=3)
    c, _ = draw(rows, per_stratum=20, seed=4)
    assert [x["message"] for x in a] == [x["message"] for x in b]
    assert [x["message"] for x in a] != [x["message"] for x in c]


@case
def test_ansi_colour_does_not_hide_an_error():
    """In "\x1b[31mFAILED" the char before F is "m", a word character, so
    \\bfail(ed)? never matches and a red FAILED reads as routine. CI, Docker
    and Kubernetes colour by default, so this silently suppressed errors in
    exactly the streams people most want triaged."""
    from neos.stream import ADAPTERS, strip_ansi
    from neos.triage import NEEDS_ACTION
    import json as _j
    by = {a.name: a for a in ADAPTERS}
    ev = by["syslog-iso"].parse(
        "2024-10-29 12:54:06-07 h svc[1]: \x1b[31mFAILED\x1b[0m to mount")
    assert ev.message == "FAILED to mount", repr(ev.message)
    assert NEEDS_ACTION.search(ev.message)
    j = by["ndjson"].parse(_j.dumps({"level": "\x1b[31mERROR\x1b[0m",
                                     "message": "x", "logger": "svc"}))
    assert j.level == "ERROR" and j.severity == 1, (j.level, j.severity)
    assert strip_ansi("\x1b[1;31ma\x1b[0mb") == "ab"


@case
def test_settle_mark_covers_every_key_a_hand_writes():
    """_settled_mark replaced a json.dumps that was 39% of runtime. If a hand
    starts writing a key the fingerprint does not read, the settle loop stops
    noticing that round's work."""
    import inspect, re as _re
    from neos.triage import rule, _settled_mark
    src = inspect.getsource(rule)
    written = set(_re.findall(r'case\["(\w+)"\]', src)) | \
              set(_re.findall(r'case\.setdefault\("(\w+)"', src))
    seen = set(_re.findall(r'case\.get\("(\w+)"\)', inspect.getsource(_settled_mark)))
    missing = written - seen - {"dispose"}
    assert not missing, f"settle loop writes {missing} but the fingerprint ignores them"


@case
def test_rfc5424_reads_severity_from_the_pri_rather_than_guessing():
    """<131> is facility 16, severity 3 = err. Reading it means confidence
    1.0 instead of 0.70, so UNSURE stays informative."""
    from neos.stream import ADAPTERS
    by = {a.name: a for a in ADAPTERS}
    ev = by["rfc5424"].parse("<131>1 2026-09-13T07:45:04Z h app 1 - - boom")
    assert ev.level == "err" and ev.severity == 1, (ev.level, ev.severity)
    assert by["rfc5424"].parse("<134>1 2026-09-13T07:45:04Z h app 1 - - x").level == "info"


@case
def test_logfmt_does_not_claim_lines_that_merely_contain_equals():
    """A loose logfmt adapter would win detection on every stream and parse
    half the world into nonsense."""
    from neos.stream import ADAPTERS
    by = {a.name: a for a in ADAPTERS}
    assert by["logfmt"].parse("2024-10-29 12:54:06-07 h svc[1]: a=b") is None
    assert by["logfmt"].parse("x=1") is None, "one unrecognised key is not logfmt"
    assert by["logfmt"].parse('level=error msg="x"') is not None


def main():
    p = f = 0
    for c in CASES:
        try:
            c(); p += 1; print(f"  PASS  {c.__name__}")
        except AssertionError as e:
            f += 1; print(f"  FAIL  {c.__name__}: {e}")
    print(f"\n  {p} passed, {f} failed")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
