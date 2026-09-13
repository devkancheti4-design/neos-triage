# Reviewed as four different people

Not imagined — run. Every number below came from executing the thing.

## What the review found before any opinion

Three real bugs, all now fixed, all found by asking an ordinary adoption
question and then actually running it:

| question | finding |
|---|---|
| "does it work on my CI logs?" | **ANSI colour silently suppressed every error.** In `\x1b[31mFAILED` the `m` is a word character, so `\bfail` never matched. Docker, CI and Kubernetes colour by default. |
| "how fast is it?" | **`json.dumps` was 39% of runtime** — 8 serialisations per event to ask "did anything change?" — while `route()`, the law, was 2.4%. Now 1.93× faster with a byte-identical verdict stream over 139,599 events. |
| "does it read my logs?" | **logfmt and RFC5424 had no adapter.** Grafana/Loki/Prometheus and the syslog wire format both came back UNREADABLE. |

Measured after the fixes:

    throughput      38,997 events/sec/core        3.37 B events/day/core
    memory          22 MB peak, flat over 500,000 events, cap respected
    robustness      no crashes, no fall-throughs: 1 MB lines, null bytes,
                    RTL text, regex-bomb shapes, log-injection attempts
    formats         syslog ISO/BSD, RFC5424, ndjson (klog, zap, DCGM,
                    python-json), logfmt, dotnet
    dependencies    zero. no network, no subprocess, no exec — by test

---

## Engineer

**Ships today.** `pip install`, zero dependencies, a library API where exactly
one branch can cost a token. k8s klog, Go zap, python-json and DCGM-style
events all dispose sensibly — a `CRITICAL` GPU fault pages.

**What would annoy them:** with no level field, actionability is English-bound
— `échec`, `Fehler`, `错误` all read as routine. A keyword list is not a
language model, and the honest fix is "emit a level field", which is now
documented rather than hidden.

## Team lead

**Can the team own it?** 26 tests, and two properties are *proved* rather than
sampled: the hand set is total over all 64 packet shapes, and the decision
path imports nothing.

**What blocks ownership:** there is no daemon. Dedup resets per invocation, so
a cron loop re-pages. No metrics endpoint, no health check, single-threaded.
It shards cleanly — the signature is a pure hash of `(ident, normalised
message)`, so N workers never need to talk — but nobody has written that.

## Engineering manager

**The saving is real and smaller than the headline.** 75.9% against a lean
batched classifier, which is what a competent team actually ships. Against
"a full agent on every event" it is 99.5%, and that is a strawman.

**The risk is honest:** it is advisory, it cannot act, so the on-call downside
is bounded. The integration cost is a person-week nobody has budgeted.

**The blocker is 71.2% incident recall**, 95% CI [58.6%, 81.2%], with
false-page rate **unmeasured**. That is a filter to run beside your alerting.
It is not a thing you turn off PagerDuty for.

## CTO

**Trivial to approve, hard to depend on.** Apache-2.0, zero dependencies, no
network, no `exec`, no `subprocess` — all enforced by test, not claimed. That
is a smaller security review than almost anything else you will adopt this
quarter.

**Strategically it is not a product.** It is one filter with a bus factor of
one and a 71.2% recall number. The interesting property is architectural: the
laws never see words, so text arriving in an event cannot reach the control
path. Injection is structurally impossible rather than defended against.

---

# By organisation

**NVIDIA-scale.** 39k events/sec/core and 22 MB flat is fine, and it shards
without coordination — but a fleet emitting 10⁹ events/day needs that sharding
written, plus OpenTelemetry and Prometheus integration that does not exist.
DCGM-shaped JSON already triages correctly, which is the encouraging part.
**Verdict: a component, after someone builds the distribution layer.**

**Anthropic-scale.** The architectural claim is the interesting one: the
decision path imports nothing and cannot be reached by text, so it is
auditable in a way a prompted classifier is not. Against that, 71.2% recall
and an unmeasured false-page rate make it a research artifact rather than
infrastructure — and the honest read of `FAIR.md` is that it scored **0%**
until last week. **Verdict: interesting as an architecture, not yet as infra.**

**Small companies.** Here the pitch is simply wrong. At 10⁴ events/day the
token saving is **single-digit dollars a month** — `ECONOMICS.md` measured
$85/year on a real personal mailbox. Nobody integrates a tool for $85.
If it is worth anything at this size it is worth it for **noise reduction**,
not tokens: 96% of a stream suppressed so a two-person team reads ten alerts
instead of three hundred. **Verdict: right tool, wrong reason — and at this
volume the 28.8% of incidents it misses costs more than the tokens it saves.**

---

# The one-line verdict

**Adopt it as a filter, at volume, beside what you have.** The engineering is
sound and the properties that matter are proved. What is missing is not code:
it is evidence that the 96% it suppresses deserved suppressing, and only a
shadow deployment with a human labelling a sample produces that. `neos label`
and `neos score` exist for exactly that, and nobody has run them yet.
