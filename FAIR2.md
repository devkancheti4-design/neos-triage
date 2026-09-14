# The fair test, second oracle

`FAIR.md` measured incident recall — 71.2% — but could not measure
false-page rate: its oracle had no clean runs. This one has 167. It is also
on `install.log`, **the stream every economic number in this repository
rests on**, whose correctness had never been measured at all.

    python3 fairtest2.py     # the number
    python3 fairtest2f.py    # the fix, time-split, with sensitivity
    python3 fairtest2g.py    # what the fix costs and saves

## Ground truth that is not mine, again

`/Library/Receipts/InstallHistory.plist` is macOS's own record of installs
that **completed** — 167 of them, written by the installer framework, not by
the log and not by this tool. The receipts and the log align to within two
seconds (`19:54:08` UTC in one, `12:54:06-07` in the other).

Pre-registered before looking at output:

| | |
|---|---|
| **ROUTINE** | an install with a receipt; its installer-process events in the 600s before it are routine by definition |
| **FALSE PAGE** | the tool paged or wrote a runbook on ≥1 event of such an install |
| **metric** | false-page rate = installs falsely paged / installs with receipts, unit = the install |

Declared weakness, first: a successful install can still contain a transient
a human would want to see. This is an **upper bound on nuisance**, not proof
each page was wrong.

## The number

    installs with events in window   167 / 167
    falsely paged or runbook'd       127
    FALSE PAGE RATE                  76.0%   95% CI [69.0%, 81.9%]

Three of every four successful installs got a page. What it paged on:

    2991x  Package Authoring: error running installation-check script: TypeError: null is n
     285x  PackageKit: Registered a global authorization to daemon, the daemon will be unab
      71x  -[SUOSUManagedServiceDaemon allDeclarationsRemovingInvalidDeclarations:]_block_i

Apple boilerplate that contains the word "error". `NEEDS_ACTION` and
`DURABLE` both fire, and the round writes a runbook. The boundary, again —
and this time as false positives, where the language-bound regex had only
been seen producing false negatives.

Dedup does not help this: **as deployed it is still 127/167**, because the
first occurrence in every window still pages. But the *token* picture is
different from the *install* picture: only **7.4%** of decode spend lands
inside successful installs. The other 92.6% fires on installer events with no
receipt at all — and this oracle cannot say whether those are real failures
or a daemon checking for updates. Absence of a receipt is not failure.

## Turning the oracle into a boundary

If the receipts know which events are routine, the boundary can be told.
**Time-split, so there is no circularity:** 96 receipts before 2026-01-01 seed
a set of routine signatures; 71 receipts from 2026 are the test and were never
seen during seeding.

First attempt — every signature that paged inside a seed window is routine:

    false-page on 2026 installs   46/71  64.8%   ->   8/71  11.3%
    pages kept outside receipts   1,921         ->   203

A five-fold drop, on unseen data, with the laws untouched. But the seed's
own provenance exposed a flaw. Prevalence across the 96 successes:

    51/96   -[SUOSUManagedServiceDaemon allDeclarationsRemovingInvalidDeclarations
    28/96   PackageKit: Registered a global authorization to daemon
    24/96   Package Authoring: error running installation-check script
     4/96   SUInstallOperation had errors preventing the install from continuing
     4/96   SoftwareUpdate: failed pre-install preflight for products
     4/96   SUInstallOperation: Will NOT continue install after product ... volume-check

**The bottom three are real failures.** They landed inside the window of an
*unrelated* product's success — window bleed — and the naive seed marked
them routine. A boundary that hides "had errors preventing the install from
continuing" is worse than no boundary. Not shippable.

## The fix, with its parameter shown rather than tuned

Boilerplate is what appears in *most* successes; a transient appears in a
few. So a signature is routine only above a prevalence threshold — and since
that threshold is a free parameter chosen after seeing data, here is the
whole sweep:

    min prevalence  seed sigs  2026 false-page  95% CI          kept outside  real failures hidden
             0%          9      8/71   11.3%  [ 5.8%, 20.7%]        203         3  <-- HIDES REAL FAILURES
             5%          6      8/71   11.3%  [ 5.8%, 20.7%]        203         0
            10%          5     12/71   16.9%  [ 9.9%, 27.3%]        518         0
            20%          4     26/71   36.6%  [26.4%, 48.2%]      1,062         0
            40%          1     46/71   64.8%  [53.2%, 74.9%]      1,921         0

The rule was stated before the sweep: *the smallest threshold at which no
real-failure signature is suppressed.* That is **5%**. It gives the identical
false-page rate to the flawed seed — the three real failures were never what
was reducing it — while keeping all three visible.

What the 5% boundary suppressed outside receipts, in 2026 (1,718 pages):

     805x  Package Authoring: error running installation-check script
     544x  -[SUOSUManagedServiceDaemon invalidAndRemoveOldDeclarations]: Removed 0
     315x  -[SUOSUManagedServiceDaemon allDeclarationsRemovingInvalidDeclarations
      54x  PackageKit: Registered a global authorization to daemon

The same four boilerplate lines, firing when `softwareupdated` runs a check
with nothing to install. And what it **kept** (203 pages, 13 distinct):

      85x  SUScan: Error encountered in scan: NSURLErrorDomain Code=-1009 "Can't connect"
      85x  Scan got error Can't connect to the Apple Software Update server
       7x  Didn't get a response from the Apple Software Update server
       3x  Timed out while loading data from the Apple Software Update server

Every kept page is a genuine event — the machine could not reach Apple.
Whether that deserves a *page* rather than a ticket is policy, but it is
signal, and the boundary dropped the noise around it and nothing else.

## What it costs and saves

Whole stream, both sides on the same safe dedup — the `ALERTS.md` accounting:

    min prevalence   decodes   lean tok/ev   neos tok/ev   saving
    laws alone         2,843          30.9           7.5    75.8%
    5%                   280          30.3           0.7    97.6%
    10%                  775          30.4           2.0    93.3%
    40%                2,833          30.9           7.4    75.9%

**2,843 decodes → 280.** The 75.8% in `ALERTS.md` was the laws alone;
**97.6%** is the laws plus a boundary the oracle wrote. Not one law changed.

## What this is, and what it is not

It is `neos seed`: give it the timestamps of known-good outcomes from any
independent record — receipts, exit codes, a deploy ledger — and it returns a
routine set with full provenance (which signature, in how many windows, an
example line), applied with `--routine`. It can only *hide* rulings on
proven boilerplate; it cannot promote anything.

It is **not** a law and it is **not** portable. It is fitted to this machine's
Apple boilerplate and will do nothing for yours until you seed it from your
own oracle. That is precisely *"a boundary per input type"* — item three —
and the oracle that produced it is item two. Both were the years. This is
one week of them, on one stream, and it moved the false-page rate from
**76% to 11%** and the token saving from **76% to 98%** without the laws
being consulted.

## Bugs in this file's own history

Mine:
1. **Naive seeding hid three real install failures** via window bleed. Caught
   by printing the seed's provenance before trusting its number.
2. My first sort fell through to comparing `Event` objects on timestamp ties
   and crashed; importing `fairtest2` re-ran its whole measurement. Both fixed.
3. I nearly reported 97.6% from the flawed seed. The number was right; the
   seed behind it was not.

Laws: **0**.
