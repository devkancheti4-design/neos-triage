# Where this is actually worth money

Mail was the ambiguity proof. Words are the hardest thing to turn into a
packet, so laws that hold on mail hold anywhere — but `ECONOMICS.md` ended
with the condition attached:

> ~79% fewer tokens **provided the encoder is cheap.** The laws are free. The
> encoder is the entire bill.

Which means **mail is this architecture's worst case**, not its best. A model
has to read every message. The best case is the inverse: a stream that arrives
**already structured**, where encoding is field extraction and costs *nothing*.

That is most of what enterprises actually run at volume — observability
events, SIEM/EDR alerts, CI failures, payment and settlement exceptions, claim
lines, device telemetry. All of it lands as fields, and all of it is currently
having LLMs pointed at it.

## The test

`/var/log/install.log` on this machine. **215,089 real events**, four years of
them, nothing invented. `route()`, `redial()`, `decline()`, `hazards()` and
`doubts_actions()` imported **unedited**. Only the hands are new, because
hands are supposed to be.

    python3 alerts.py /var/log/install.log

## Result

    WHERE THE REDUCTION COMES FROM
      dedup     215,089 ->   6,158    97.14%   a hash set. NOT a law.
      laws        6,158 ->      43    99.30%   on what survived dedup
      net       215,089 ->      43    99.98%   events that ever become words

    TOKENS PER EVENT              in      out    total
      LLM on every event       4,024    1,050    5,074
      LLM on deduped events      115       30      145
      lean batched classifier    0.7      0.6      1.3
      neos (laws + decode)       0.1      0.0      0.1

    $ / MILLION EVENTS          Opus 5   Sonnet 5   Haiku 4.5
      LLM on every event        46,371     18,548       9,274
      LLM on deduped events      1,328        531         266
      lean batched classifier       18          7           4
      neos                           2          1           0

## The three honest deductions

**1. Most of that is a hash set, not a law.** 97.14% of the reduction is
dedup — any competent pipeline does it, and it deserves no credit here. The
laws' own contribution is what happens to the 6,158 that survive: they dispose
of 99.30% of those with zero tokens.

**2. Compare against a competent baseline, not a strawman.** "LLM on every
event" with a 4,000-token agent prompt and adaptive thinking is not what
anyone builds for log triage. The real competitor dedupes first, batches 50
events per call, uses a lean prompt and no thinking, and emits one verdict
each: **45.2 tokens per distinct event.**

The laws spend **4.9**.

    vs LLM-on-everything     99.997% fewer tokens
    vs LLM-on-deduped        99.904% fewer tokens
    vs LEAN BATCHED           89.19% fewer tokens    <- the fair fight

~~**89%, not 99.99%.** That is the number to quote.~~

> **CORRECTED — see [FAIR.md](FAIR.md).** That 89% was measured on a tool
> with **0% incident recall**. The dedup this document credits with 97.14%
> of the reduction was hiding a real failure that recurs 1,113 times, and
> 59 of 59 independently-attested incidents were suppressed. With dedup made
> safe (windowed, laws first), recall is 71.2% and the saving is **75.9%**.
> Safety cost 13 points. The 89% was not a better result -- it was the same
> result with the incidents removed.

**3. Two properties of this stream that are not wins.**

*Three of eight doubt bits are dead.* `UNSURE` never fires because the encoder
is exact — the bit that was pinned high on **100%** of mail packets is simply
absent here. But `CLAIMED` is constant for the opposite and worse reason: my
`encode()` sets `asserts=True` unconditionally. I criticised `UNSURE` for
exactly this and then did it myself one file later. A log line always claims a
state, so the bit is constant *by the nature of the domain* — which makes it a
bit this domain doesn't need, not a bit that is working.

*`DECLINE` never fires, and that is not a pass.* ~~`PAIR` never co-occurs with
`FULL` on this stream, so no round is ever short of voices.~~

> **CORRECTED.** This was wrong, and it was wrong because of a bug of mine one
> file away. The round in `neos/triage.py` dropped `or pkt.summary` when it was
> ported from `the reference implementation these laws were first written for`, so any event that parsed cleanly but
> carried no extractable values read as `UNSHAPED` and the law declined to open
> a round at all. `DECLINE` had nothing to refuse because `ROUTE` was returning
> `NONE` first.
>
> With the port bug fixed, **`DECLINE` fires on real events**: 7 in
> `cowork_vm_swift.log`, every one a CA-certificate install or a disk creation
> — state changes that set `COSTLY`, demand `FULL`, and get `PAIR`. The refusal
> path works, on a real stream, unprompted.
>
> The original claim is left visible above rather than quietly deleted. It was
> published, and the correction is the point: an untriggered safety mechanism
> and a *masked* one look identical from the outside, and I reported the first
> when it was the second. See `DEPLOY.md`.

---

# What this says about the architecture

The mail result and this one are the same result seen from two ends.

**The laws cost nothing in either domain.** What changes is the price of the
boundary. On words the boundary is a model and dominates the bill; on
structured events the boundary is `re.match` and is free. So the honest
statement of where this pays is not "AI is expensive, use logic" — it is:

> The architecture converts *decision* cost into *encoding* cost. It wins
> exactly where encoding is cheaper than deciding, and that is every stream
> that already has fields.

Mail proved the laws survive ambiguity. Logs are where they pay for
themselves. Neither result needed a line of the laws changed.

# Bugs

Laws: **0**.

Mine:
1. Wrote `asserts=True` unconditionally, pinning `CLAIMED` at 100% — the
   identical defect I had just written up as `UNSURE`'s.
2. Printed "Two of eight doubt bits are dead" when the count was three.
3. Led with a 4,000-token strawman baseline before adding the lean batched
   classifier that a real team would deploy. 99.99% became 89%.
4. **Published "DECLINE never fires" as a property of the domain.** It was a
   bug in my port of the round, not a fact about logs. Corrected above.
