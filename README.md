# neos-triage

**Triage structured event streams by exact law. No model in the decision.**

    pip install neos-triage
    neos /var/log/syslog

An LLM triaging events spends most of its tokens deciding whether an event
matters. That decision here is a handful of bit operations over a byte — so it
costs nothing, and a model only writes words for the ~1% that survive.

**75.9% fewer tokens** than a lean batched classifier, measured on 215,089 real
events with both sides using the same safe dedup. → [USAGE.md](USAGE.md)

## Read this before you deploy it

Measured against ground truth the tool cannot see — filesystem-check exit codes
recorded in a separate file — it caught **42 of 59** real incidents: **71.2%
recall, 95% CI [58.6%, 81.2%]**.

As originally shipped it caught **0 of 59**. A dedup credited with 97% of the
token saving was hiding a failure that recurs 1,113 times. Fixing it cost 13
points of the saving, because the 89% published earlier was the same result
with the incidents removed.

**False-page rate is still unmeasured.** Run it beside your existing alerting,
not instead of it. `neos label` / `neos score` produce the evidence for your
own stream. → [FAIR.md](FAIR.md), [DEPLOY.md](DEPLOY.md)

## How it works

    event ──[adapter]──► PACKET ──► ROUTE ─ hands settle ─► REDIAL ──► DECLINE
              a regex                  every step below is bit operations

`route()`, `redial()` and `decline()` are verified against compiled C kernels
over **all 256 inputs**. Nothing is trained, tuned or fitted. The laws never
see words — an adapter converts at the boundary and decides nothing, which is
why text arriving in an event cannot reach the control path.

Adapters auto-detect: syslog (ISO and BSD), `.NET`/Unity, tagged, NDJSON.
Below a 50% parse rate it **refuses** rather than reporting a confident 0%.

## What it will not do

It reports. It cannot send, write, execute or act — no `subprocess`, no
`exec`, no network, **zero dependencies**, all enforced by tests rather than
claimed.

## Tests

    python3 tests/test_triage.py    # 22
    python3 fairtest.py             # incident recall vs an independent oracle

Two properties are *proved*, not sampled: the hand set is **total** over all 64
packet shapes — no event is ruled and then dropped — and the decision path
imports nothing.

## Licence

Apache-2.0. The sibling project that carries fluidfix's AGPL kernel is not
distributed here.
