# Testing the claim

> *"in time it will be accurate or makes millions to billions and various
> applications"*

Three claims. All three testable. Here is what happened when they were tested
rather than argued about.

---

## 1. "In time it will be accurate" — TRUE, but not because of time

Incident recall against ground truth the tool cannot see, measured three times
in one week:

    as first shipped                             0.0%
    dedup made safe (windowed, laws first)      71.2%   [58.6%, 81.2%]
    + a second input (the exit code)            81.4%   [69.6%, 89.3%]

The trend is real and it is steep. But **nothing about it was time passing**,
and — this is the part worth keeping — **not one of those gains came from a
law.** `route()`, `redial()` and `decline()` are byte-identical to the day
they were generated.

### Why the missing 28.8% could never have been fixed by a law

Here is an entire run the tool missed, with the oracle recording exit code 65
(**failed**) for it:

    fsck_apfs started at Mon Sep  7 22:33:58 2026
    ** QUICKCHECK ONLY; FILESYSTEM CLEAN          <-- the log says CLEAN
    fsck_apfs completed at Mon Sep  7 22:33:58 2026

The stream says the run was clean. The exit code says it failed. **The
information needed to catch it is not in the stream — the stream asserts the
opposite.** No law, no encoder and no frontier model reading that text could
classify it as an incident, because the text is wrong.

Feeding the exit code in as a **second eye** — a new input, not a new law —
took recall from 71.2% to 81.4% immediately.

The remaining 11 misses are not a tool failure either: the exit-code file
records 13 entries covering 42 distinct runs, so it does not say *which* of
several same-second runs failed. That is a resolution limit in the ground
truth.

### So the claim is right with one word changed

**Accuracy improves by adding EYES, not by adding laws and not by waiting.**
That is the same finding this architecture has produced in every domain it has
touched — on video it was *"the fix is a second independent eye, not a law
change"*; on mail it was *"the encoder is the bottleneck at both ends"*; here
the signal is simply absent. The laws have never once been the limit. The
boundary always is.

That is not a small claim. It means accuracy is an **engineering** variable,
not a training one — you buy it with another sensor, and you can predict what
it will cost before you spend it.

---

## 2. "Millions to billions" — millions yes, billions conditionally

Saving is 76.1% against a lean batched classifier. What that is worth:

    model        $/M events saved   events/day for $1M/yr   for $1B/yr
    Opus 5                    312                  8.8 M        8.8 B
    Sonnet 5                  125                 21.9 M       21.9 B
    Haiku 4.5                  62                 43.9 M       43.9 B

**$1M/year needs 8.8M events/day.** That is *one* large Kubernetes fleet.
Ordinary large enterprises do 1–10 **billion** log lines a day — a hundred to
a thousand times that threshold. So millions is not a stretch; it is arithmetic.

**$1B/year needs 8.8B events/day** on Opus. That volume exists — a large SaaS
or any hyperscaler clears it. So the number is reachable in principle.

### The condition that decides it

**You cannot save money nobody is spending.** This 76.1% is measured against
*an LLM triaging every deduplicated event* — and almost nobody does that today.
Today people run Prometheus rules and grep, which cost **$0**, and against that
baseline the saving is **zero**.

So "millions to billions" is not a claim about this tool. It is a bet that
**LLM triage becomes the default first.** If that happens, the arithmetic above
is conservative. If it does not, the value of this is noise reduction rather
than tokens — real, but not measured in millions.

Worth stating plainly: the bet is reasonable. The direction of travel is
toward models reading everything.

---

## 3. "Various applications" — already demonstrated, six times

The same unedited laws have now ruled on:

| domain | what the packet was |
|---|---|
| email | asks / commits / time-bound, from a transducer |
| system logs | severity, durability, deadline, from a regex |
| video | centroid, extent, velocity, from a luminance eye |
| multi-object tracking | detections and identity over frames |
| 3D / LiDAR | returns and point clusters |
| alerting | exit codes and levels |

In every one, the laws were imported rather than rewritten, and in every one
the failure was at the boundary. Six domains is not "various" as an aspiration
— it is a measured property.

---

# The verdict

**The claim survives, with its mechanism corrected.**

* Accuracy: **improves with inputs, not time and not laws.** 0% → 71.2% →
  81.4% in a week, every gain at the boundary.
* Money: **millions is arithmetic** at one large fleet's volume; **billions is
  a bet on LLM triage becoming standard**, not a property of the tool.
* Applications: **already six**, with the laws unedited each time.

The thing that would most change these numbers is not another law. It is a
second sensor on a stream that matters, and a human labelling two hundred
events so the recall interval stops being eleven points wide.
