# The fair test

> *"A suppressed event is only a saving if it deserved suppressing. Tokens not
> spent on an incident you missed aren't saved, they're deferred at interest."*

So: measure it. `python3 fairtest.py`

## Getting ground truth that isn't mine

I built the tool. Labelling its output myself is the definition of an unfair
test, so the ground truth had to come from somewhere I don't control.

**`/var/log/fsck_apfs_error.log`** records a numeric exit code for every fsck
run — `result=0` clean, `result=65` did not complete — written by Apple's
`fsck_apfs` into a **separate file**. The tool never reads it. The tool reads
only `/var/log/fsck_apfs.log`, the human-readable stream.

Pre-registered before looking at any tool output:

| | |
|---|---|
| **INCIDENT** | an fsck run whose independently-recorded exit code is non-zero |
| **CAUGHT** | the tool surfaced ≥1 event of that run (page / runbook / ticket / held) |
| **MISSED** | the tool suppressed **every** event of that run |
| **metric** | INCIDENT RECALL = caught / (caught + missed) |

The unit is the **run**, not the line. Suppressing 97% of lines is fine if one
line per incident still reaches a human — that is exactly what recall measures.

Declared weakness, stated before the result: every failing run contains the
literal string `error:`, and the tool's `NEEDS_ACTION` pattern contains
`error`. So a high score would be a **floor, not a triumph**. The ablation
below deletes that word and re-runs; the gap is what the laws contribute
beyond matching one keyword.

## The result

    AS SHIPPED          incidents 59    caught  0    MISSED 59
                        INCIDENT RECALL  0.0%   95% CI [0.0%, 6.1%]

**Zero.** Fifty-nine real, independently-attested failures, every one
suppressed. The tool would have saved every token and lost every incident.

### Why

`error: container /dev/rdisk1 is mounted with write access` occurs **1,113
times**. Dedup saw it once, in 2024, and hid it for the next two years. Every
later failed fsck run was invisible.

I had credited dedup with **97.14%** of the token saving and written that it
"deserved no credit — it is a hash set, not a law." I checked that it was not
a law. **I never checked that it was safe.**

## Three fixes, two of them wrong

**1. Rule first, dedup second.** The laws cost zero tokens, so putting a hash
set in front of them buys nothing and costs incidents. Dedup belongs in front
of the *expensive* step (decode), which is what it now gates.
→ still **0%**.

**2. Exponential re-alert** — surface on occurrence 1, 2, 4, 8, 16…
→ still **0%**. By occurrence 900 the next surfacing is 1024, so 124
consecutive incidents stay invisible. Backoff is the wrong shape for safety.

**3. Windowed dedup.** The real defect was deeper than frequency: **the same
signature legitimately recurs across independent incidents.** 59 separate fsck
runs each emit a byte-identical line. Global-forever dedup cannot tell them
apart; bucketing by time can. Two failures five minutes apart are two
failures. Where a stream carries no usable timestamp it falls back to every
20th occurrence, which bounds how many can hide in a row.

    AS SHIPPED NOW      incidents 59    caught 42    MISSED 17
                        INCIDENT RECALL 71.2%   95% CI [58.6%, 81.2%]

    'error' ABLATED     INCIDENT RECALL 71.2%   — identical

## Two things worth noticing

**The laws are not keyword matchers.** Deleting `error` from every line
changes recall by nothing. The signal is `mounted` → durable state →
`COSTLY` → demands `FULL` → gets `PAIR` → **`HELD`**. Every one of the 42
catches is a *refusal*, not a page: the law surfaces these by declining to
dispose of them, which is the `DECLINE` path that `ALERTS.md` originally and
wrongly reported as never firing.

**71.2% is not good enough.** 17 of 59 incidents still missed, upper bound
81.2%. This is not a decider. It is a filter that must sit beside something
else.

## What safety cost

Both sides using the **same** safe dedup:

    TOKENS PER EVENT                install.log, 215,089 events
      full agent, every event              1,476.6
      lean batched classifier                 30.9
      neos (laws + decode)                     7.4

      vs lean batched                    75.9% fewer tokens

**Down from the 89.2% published in `ALERTS.md`** — and that 89.2% was measured
on a tool with **0% incident recall**. Decode now fires on 2,835 events rather
than 41, because 2,794 events the laws wanted to surface were being hidden.

> **Safety cost 13 points of the saving. The 89.2% was not a better result;
> it was the same result with the incidents removed.**

## Limits of this test

* **n = 59 incidents, one machine, one subsystem.** The interval is wide and
  it says so.
* **The oracle has no clean runs.** `result=0` entries carry an empty `dev=`
  field and could not be joined, so **false-page rate is unmeasured here.** A
  tool that pages everything would also score 71.2% on this test. The
  install.log false-page rate is still unknown.
* **2,235 runs had no oracle entry** and were excluded rather than guessed at.
* I wrote both the tool and the test. The oracle is independent; the framing
  is not. A second pair of eyes is still owed.
