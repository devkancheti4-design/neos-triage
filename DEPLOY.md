# Deploying this, honestly

    pip install -e .
    neos /var/log/install.log
    neos --json /var/log/syslog | jq 'select(.disposition=="page")'
    tail -f app.log | neos - --format ndjson --json

`neos-triage` is a CLI and a library. **Zero dependencies.** No network, no
model, no subprocess, no `eval` — all four enforced by tests, not claimed.

---

## What is actually proven

| property | how |
|---|---|
| the laws are exact | bit-identical to `route.c` / `joint2.c` over **all 256** inputs |
| the hand set is **total** | exhaustive over all **64** packet shapes — no event is ruled and then dropped |
| memory is bounded | LRU dedup, capped; tested at 10,000 signatures into a cap of 100 |
| no dependency, no network | AST-walked in a test; the ban list includes `socket`, `urllib`, `anthropic` |
| it cannot act | no `subprocess`, no `os.system`, no `exec` — it reports, a human or a downstream system acts |
| it refuses what it cannot read | below 50% parse rate it exits 3 rather than reporting a confident 0% |

**229,267 real events, five formats, one laptop, zero fall-throughs:**

    stream                       adapter       events  distinct  suppress  ticket  page  runbook  held
    install.log                  syslog-iso   215,089     8,500     8,283     166    10       41     0
    system.log                   syslog-bsd        83        14        14       0     0        0     0
    Unity.Licensing.Client.log   dotnet        11,056       532       497      14    14        7     0
    cowork_vm_swift.log          tagged         2,357       847       840       0     0        0     7
    updater_history.jsonl        ndjson           682       366       366       0     0        0     0

---

# What is NOT proven, in order of how much it should worry you

## 1. Ground truth now exists for ONE subsystem, and it found a zero

[FAIR.md](FAIR.md) tests the tool against fsck exit codes recorded in a
separate file the tool never reads. As shipped, it scored **0% incident
recall** — 59 of 59 real failures suppressed, because dedup hid a line that
recurs 1,113 times. Fixed (windowed dedup, laws before the hash set) it
scores **71.2%**, 95% CI [58.6%, 81.2%].

**71.2% is still not a decider.** And false-page rate remains unmeasured:
that oracle had no clean runs, so a tool that paged everything would score
the same. Everything below still applies.

## 1b. For every other stream, there is still no ground truth.

Everything above measures what the tool **does**. Nothing measures whether it
is **right**. No operator has confirmed that those 10 paged events deserved a
page, or — far more dangerous — that the **8,283 suppressed events were safe
to suppress**.

Suppressing 97% of a stream is only a good result if it is the *right* 97%.
A tool that suppresses 100% also scores 97%.

For mail there was ground truth: the account's own sent replies said what a
human actually did. **Here there is none, and I did not manufacture any.**

> **Do not put this in front of production alerting as the decider.** Run it
> in shadow beside whatever you have now, diff the two for a few weeks, and
> have someone label a sample of the suppressions.

**The harness for that now exists** (`neos/label.py`):

    neos label /var/log/install.log -o review.jsonl
    #  -> 130 events, STRATIFIED: all 10 pages, 40 suppressions, 40 tickets...
    #  a human fills in the "human" field: "ok", or what it should have been
    neos score review.jsonl

Sampling is stratified because the dangerous classes are the rare ones: a
uniform 200-event sample of `install.log` would be ~195 suppressions and would
measure the paging decision not at all. Strata sizes are recorded, so the
extrapolation back to the stream is valid:

    FALSE SUPPRESSION -- the error that loses an incident
      rate 5.0%   95% CI [1.4%, 16.5%]
      extrapolated to the stream: 114 to 1,367 of 8,283 suppressed events
      UPPER BOUND IS 16.5%. Not safe as a decider until this interval
      is tight AND low.

Intervals are **Wilson**, not normal-approximation: 0 failures in 40 samples
must read as "up to 8.8%", never as "0%". A clean small sample is not
evidence of safety and the tool will not let it look like one.

*(The figures above are a mechanism test on synthetic labels. **No real
labelling has been done.** That still needs an operator.)*

## 2. Five formats, one laptop

No journald, no Kubernetes events, no Windows Event Log, no Splunk/Datadog/
Elastic export, and — notably — **no Linux syslog at all**. Adapters are ~10
lines each (`neos/stream.py`) and detection picks the best match on a real
sample, so adding one is cheap. But "works on five macOS formats" is not
"works on your stream," and detection **refuses** rather than guessing.

## 3. The hands are my judgement, not your policy

`asks = severity <= 2`. `Page` = actionable *and* time-bound. `Runbook` =
actionable *and* state-changing. Those thresholds decide what wakes someone at
3am and I chose them in an afternoon. **Every site's answer differs.** The
laws are fixed; the hands are supposed to be replaced, and `neos/triage.py`
is where you do it.

## 4. Operational gaps

* **No state across runs.** Dedup resets each invocation, so a cron loop
  re-pages the same thing. A daemon needs persistence; there isn't one.
* **No flap detection** across time windows — only "seen before in this run."
* **English regexes** (`NEEDS_ACTION`, `DURABLE`) are used *only* when a
  format carries no level field. Where a level exists it is read, not guessed.

## 5. The licence blocks publication — and did so by accident

`pyproject.toml` referenced a `LICENSE` file **that does not exist**. It could
not have been published.

Worse, `neos/measure.py` was carrying fluidfix's kernel — `255 & ((x >> 8) +
((x >> 16) - x))` — with **no caller anywhere in the repository**. Dead code
still ships, and AGPL attaches to distribution, not to execution. So the
distributable package was inheriting AGPL-3.0-or-later **by accident**,
through a function nothing called.

It now lives in `a sibling project that is not distributed here`. `pyproject` packages only `neos`, so:

* the sibling project that carries fluidfix's kernel is AGPL-3.0-or-later and is **not** distributed here
* `neos/` — **verified free of it**, so the licence is an open choice

That choice is the author's and I have not made it. Until a `LICENSE` file
exists, nothing should be published anywhere.

---

# The honest summary

The engineering is sound and the properties that matter are proved rather than
asserted. What is missing is not code — it is **evidence that the dispositions
are correct**, which only a shadow deployment and a human labelling a sample
can provide.

Ship it as advisory. Earn the right to make it the decider.

# Bugs found while building this

Laws: **0**.

Mine, all four caught by exhaustive checks rather than by the happy path:

1. **6 of 64 packet shapes fell through** — `asks ∧ ¬commits ∧ ¬time_bound`
   was read by no disposing hand. 837 of 847 events in one real stream came
   out ruled and went nowhere. Fixed by `Ticket`, and `tests/test_triage.py`
   now proves totality the way the laws are proved total.
2. **`or pkt.summary` was dropped** porting the round from
   `the reference implementation these laws were first written for`. An event that parsed perfectly but carried no
   extractable values read as `UNSHAPED`, so the law declined to open a round
   at all — and the "no-call" rate was really measuring how much the *adapter*
   bothered to extract. A test now pins the two rounds together.
3. **`DECLINE never fires` was wrong** — I published that in `ALERTS.md`. It
   was masked by bug 2. With it fixed, 7 real events are correctly held:
   CA-certificate installs that change durable state, demanding `FULL` when
   only `PAIR` was available.
4. **Mail vocabulary leaked into a log tool.** A CA-certificate install was
   explained to an operator as committing *"money, a promise, or a booking."*
   The bits are domain-neutral; the sentences were not.
