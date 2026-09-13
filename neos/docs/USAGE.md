# Using this to cut tokens

    pip install neos-triage
    neos /var/log/syslog

## The idea in one line

An LLM triaging events spends most of its tokens **thinking about whether an
event matters**. That decision is a handful of bit operations over a byte, so
it costs nothing — and then a model only has to write words for the few events
that survive.

    event ──[adapter: a regex]──► PACKET ──► laws ──► disposition
                 free                        free      only this can cost tokens

## Where it pays, and where it does not

The architecture converts **decision** cost into **encoding** cost. So it wins
exactly where encoding is cheaper than deciding:

| your input | encode cost | worth it? |
|---|---|---|
| logs, alerts, SIEM/EDR events, CI failures, telemetry, webhooks | a regex — **free** | **yes** |
| payment/settlement exceptions, claim lines, device events | field lookup — **free** | **yes** |
| free-form text (email, tickets, chat) | a model must read every item | **usually not** |

That last row is not a hedge. On free-form text a model has to read
everything to build the packet, and if you put a frontier model at that
boundary the architecture costs **more** than just running a cheap model on
everything. **The laws are free; the encoder is the entire bill.**

## What it actually saves

Measured on 215,089 real events, both sides using the same safe dedup:

    full agent, every event             1,476.6 tokens/event
    lean batched classifier                30.9
    neos (laws + decode)                    7.4      75.9% fewer

The honest baseline is the **lean batched classifier** — dedupe first, batch
50 events per call, short prompt, no thinking, one verdict each. That is what
a competent team ships, and 75.9% is the number against it. Comparing against
"a full agent on every event" gives 99.5% and is a strawman.

It decomposes into three unequal parts:

1. **No thinking.** 800 of a full agent's 1,050 output tokens are adaptive
   thinking, billed as output at ~5× the input rate. This never thinks.
2. **No context to carry.** A full agent ships tool definitions, a policy and
   examples on every call. The laws *are* the policy, and they are compiled.
3. **Words for ~1% of events.** Everything else is disposed of in packet space.

## Measure it on your own stream

    neos /path/to/your.log

Read the last line: **"events that ever become words"**. That percentage is
your decode rate — the only part that costs anything. Multiply by your
model's per-call cost and compare with what you pay now.

    neos yourlog --json | jq -r .disposition | sort | uniq -c

## The dial that trades tokens against safety

`--window N` is how long a repeated signature stays suppressed.

    neos install.log --window 0        91.5% deduped,  1,498 decodes
    neos install.log --window 300      35.1% deduped,  2,835 decodes   (default)
    neos install.log --window 3600     47.6% deduped,  2,655 decodes

**Longer window = fewer tokens = more missed incidents.** At infinity this
tool scored **0% incident recall** on a real test, because the same signature
recurs across genuinely independent failures and forever-dedup cannot tell
them apart. Do not turn the window up to save money without re-running
`fairtest.py`-style checks on your own stream. [FAIR.md](FAIR.md) has the
whole story.

## It is English-bound unless your format carries a level

When a stream has **no level field**, actionability is inferred from English
words (`error`, `failed`, `timeout`, ...). Everything else is read as routine:

    "échec de la connexion"     -> suppressed
    "Fehler beim Verbinden"     -> suppressed
    "错误: 磁盘已满"              -> suppressed

There is no clever fix for this; a keyword list is not a language model. The
escape hatch is real though: **a format that carries its own severity is
language-independent**, because the level is read rather than guessed.
`ndjson`, `logfmt`, `rfc5424` and `dotnet` all carry one; plain syslog does
not. If your logs are not in English, emit a level field.

(ANSI colour used to cause the same silent suppression — in `\x1b[31mFAILED`
the `m` is a word character, so `\bfail` could not match. Escapes are now
stripped at the boundary.)

## Before you trust it

Measured incident recall is **71.2%**, 95% CI [58.6%, 81.2%], and false-page
rate is **unmeasured**. This is a filter to run *beside* your alerting, not a
replacement for it.

    neos label /path/to/your.log -o review.jsonl   # stratified sample
    # a human fills in the "human" field
    neos score review.jsonl                        # rates, with intervals

`neos score` reports **false suppression** — events it closed that a human
says should have been surfaced — with Wilson intervals, so 0 failures in 40
reads as "up to 8.8%", never "0%". Run that on your stream before you let it
decide anything. [DEPLOY.md](DEPLOY.md) lists what is proven and what is not.

## Certifying your own laws

    python3 -m neos.certify

    from neos.certify import certify, report
    report({"my_law": my_act_fn})     # exhaustive, ~90 ms per 8-bit law

`composable: True` means the law can be bound to others without checking the
joint space. A law that is monotone but not homomorphic will pass the review
a human performs and break composition silently — measured at 0/60.

## As a library

```python
from neos.stream import detect, read
from neos.triage import encode, rule, signature, Dedup, default_hands

adapter, rate = detect("app.log")
hands, dd = default_hands(), Dedup(window=300)
for ev in read("app.log", adapter):
    act, demand, held, obs, doubt, case, actions = rule(encode(ev), hands=hands)
    if dd.seen(signature(ev), ev.epoch):
        continue                       # a repeat inside the window
    if case.get("plan"):               # the ONLY branch that needs a model
        ...                            # send case["plan"] to your LLM
```

Nothing above touches a network. `rule()` is bit operations over a byte.
