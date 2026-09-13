# 100s of laws as the brain, models only at the boundaries

The proposal, tested rather than argued.

    words/pixels/events ──[model: translate]──► PACKET
                                                  │
                                        100s of laws, bound
                                                  │
                        PACKET ──[model: translate]──► words

Three questions decide whether this works: does the form guarantee
composability, does verification survive scale, and how do you bind them.

---

## 1. The form is the whole thing

A law here is exactly what the superoptimizer emits: `MASK(x)` is a pure OR
of terms that each target **one bit**, plus a constant floor; the act is
`ctz(MASK(x))`.

60 laws of that form, against 60 laws that use the same tiers but let a lane
depend on a **combination** of bits — which is what hand-writing produces:

    population     n    homomorphic    monotone
    STRUCTURED    60         60/60       60/60
    ARBITRARY     60          0/60       60/60

**Monotone is not the property.** The arbitrary laws pass monotonicity — the
check a reviewer would actually run — and are homomorphic **zero times out of
sixty**. `ACT(a|b) = min(ACT(a), ACT(b))` is what lets laws compose at all,
it is invisible to inspection, and it comes from the *shape*, not the
behaviour.

**Consequence for the proposal:** every one of the hundreds must be machine
generated in that form. A law someone writes by hand, however sensible, will
almost certainly break composition while looking correct.

## 2. Verification survives scale, spectacularly

    N laws    homomorphic    verify calls    naive joint space
         1          True             256                  2^8
        10          True           2,560                 2^80
       100          True          25,600                2^800
       250             —          64,000               2^2000

Because min of homomorphisms is a homomorphism, a composition never needs its
joint space. Each law is proved once over its own 256 inputs, and the binding
inherits the property.

**100 laws cost 25,600 checks. The joint space is 2^800 — more configurations
than there are atoms.** This is the part of the proposal that is not just
sound but decisive: it is the only way a hundred-law brain is auditable at all.

## 3. Binding is where it lives or dies

    N laws     VETO binding     ROLE binding
                 refuse-all       refuse-all
         1            75.0%            75.1%
        10            99.2%            77.5%
        50            99.6%            41.3%
       250            99.6%            40.0%

**VETO** — every law judges the same observation, round opens as wide as the
narrowest allows. Refusal compounds: `P(any law refuses) → 1`. **The system
locks solid at about fifty laws.** This is the naive reading of "bind them
together", and it does not work.

**ROLE** — each law judges its own observation. A law that is not looking at
this situation cannot veto it. **Flat at 250 laws.** Adding laws adds coverage.

This is already the architecture: `route` reads the hazard byte, `redial`
reads the doubt byte, `decline` reads `(act, demand)`. Three laws, three
domains, no shared veto. Scaling to hundreds means **hundreds of domains**,
not hundreds of opinions about one.

---

## 4. "Models only for translating input and output" — measured

Same 300 units, same unedited laws, pattern encoder vs model encoder:

    RULING     local 290 READY / 6 RAISED / 3 HELD
               model 290 READY / 6 RAISED / 3 HELD      IDENTICAL

    DISPOSITION            local    model
      archive                282        4
      file_quietly             0      269

The ruling does not move by one message. What moves is what the thing is
understood to **be**, and therefore what happens to it. The model at the
boundary cannot corrupt a ruling — and cannot improve one either. **All the
leverage of a better model is in the packet; none of it is in the decision.**

That is the proposal's strongest claim and it is the one with the cleanest
evidence.

---

# What the tests say

**The proposal is sound, with three conditions that are not optional:**

1. **Every law machine-generated in the authored form.** Hand-written laws
   pass the review a human would run and fail the property that matters.
2. **Bound by role, never by veto.** Hundreds of domains, not hundreds of
   opinions. Veto binding locks at fifty.
3. **The boundary is the limit, always.** Across six domains — mail, logs,
   video, tracking, 3D, alerting — the laws have never been the failure.
   `CLAIM.md` has a run the tool missed whose log says `FILESYSTEM CLEAN`
   while its exit code says failed: no law could fix that, and a second
   sensor fixed it immediately.

**The honest limit of this file:** conditions 1 and 2 were tested with
synthetic laws of the correct form, not with a hundred real ones. What it
establishes is that the architecture *admits* hundreds — not that any
particular hundred are right. Producing those, and an oracle for each domain
they rule, is the work.
