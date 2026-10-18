# Taint: skip the runs that cannot reach a sink (#87), 2026-10-18

## Problem
Taint follows each source occurrence (origin) in its own run, once per rule. When k sources feed shared code, the runs repeat the same work, and taint grows linearly with k. The benchmark below (`k` request parameters passed to a helper with a 400-statement chain, built-in Python rules, data flow already solved) shows it:

| Sources | No sink in the helper | `os.system` at the end of the helper |
|---|---|---|
| 10 | 0.10 s, 0 findings | 0.08 s, 10 findings |
| 20 | 0.20 s | 0.17 s, 20 findings |
| 40 | 0.39 s | 0.35 s, 40 findings |
| 80 | 0.84 s | 0.66 s, 80 findings |

Most of these runs find nothing:
- Without a sink, all of them.
- With a sink, two of the three built-in rules, because only the command-injection rule's sinks are reachable.
- On ordinary files, almost all runs: CPython `Lib` gives no findings with the built-in rules.

## Approach
#87 proposes two options:
- one merged propagation of origin sets, with paths rebuilt afterwards;
- as a "safer first step", a cheap first phase that keeps per-origin runs only where they can matter.

A merged run would discover values in a different order, so the "first path found" for a finding could change; the guide and the tests pin those paths. This change takes the safer step, and keeps today's runs, findings and paths exactly:
- **Sink reach.** For each rule, compute once the set of nodes from which taint could possibly reach one of the rule's sinks. This is a backward search from the nodes whose call sites match a sink, over every edge a run can follow:
  - def-use chains;
  - free-variable flows;
  - argument flows into callees;
  - return flows into calls;
  - control dependence and match cases, when implicit flows are on.
  
  It ignores sanitizers, fields and argument positions, so it over-approximates. A run only ever moves along these edges, so an origin outside the set cannot produce a finding.
- **Skip those runs.** `analyze` runs an origin only if its node, or the function entry for a parameter source, is in the rule's set.

Not here: one merged propagation for origins that do reach a sink. Each of those yields a finding with its own path, so the remaining cost is per finding, not per source.

## Tests
- Oracle: on the taint corpus and the engine test programs, findings and paths with pruning equal those without (pruning switched off by a patch).
- Each edge kind keeps an origin alive. A sink reached only through:
  - a def-use chain;
  - an argument into a callee;
  - a return;
  - a free variable;
  - a control dependence (implicit flows);
  - a match case.
- Pruning is per rule: an origin whose rule's sinks are unreachable is not run, even when another rule's sink is reachable (spy on `_Run`).
- A sink at the origin node itself is kept.

## Measure
The benchmark above, before and after. The stress runner's taint stages on CPython `Lib`.

## Results
Executive summary: taint now skips the runs of origins that cannot reach a sink of their rule. On the benchmark, 80 sources whose shared helper has no sink take 0.004 s instead of 0.84 s. With `os.system` in the helper, they take 0.29 s instead of 0.66 s: only the command-injection rule's runs remain, one per finding. Findings and paths are unchanged on the taint corpus and in the whole test suite.

| Sources into one helper | No sink, master → branch | `os.system` at the end, master → branch |
|---|---|---|
| 10 | 0.10 s → 0.003 s | 0.08 s → 0.07 s |
| 20 | 0.20 s → 0.002 s | 0.17 s → 0.08 s |
| 40 | 0.39 s → 0.003 s | 0.35 s → 0.13 s |
| 80 | 0.84 s → **0.004 s** | 0.66 s → **0.29 s** |

On the corpora the gain is small, because after #85 taint there is mostly fixed per-file work. The stress runner on CPython `Lib` (two runs each, 3 workers):

| Stage | master | this branch |
|---|---|---|
| taint | 3.28 s, 3.34 s | 2.85 s, 3.25 s |
| taint-precise | 4.05 s, 4.01 s | 2.80 s, 3.19 s |

A first version built the reverse flow graph for every file, sources or not, and was a little slower than master on the corpora. The graph is now built only when a rule has origins.

- **Sink reach.**
  - `_Program.reaching_sinks(rule)` is a backward search from the nodes whose calls match the rule's sinks. It runs over the reversed def-use, free-variable, argument, return, control (`governed`) and match-case (`cases`) flows, built once per program.
  - Its result is cached per set of sink patterns, so rules with the same sinks share it.
  - `_Program.calling(*patterns)` is the callee-text index from #85, now shared by call sources and sinks.
- **Pruning.** `analyze` runs an origin only if its node is in its rule's reach set. Origins and runs keep their order, so the first path found for each finding is the same as before.
- **Not done: a merged run.** The remaining cost, when many sources do reach a sink, is one run per finding. Making it one merged propagation of origin sets, as #87 also proposes, would change which first path is found. It is left open.
- **Tests:**
  - an oracle on every taint corpus file: findings and paths with pruning equal those with it switched off;
  - one test per flow kind that leads back to the origin: the sink itself, def-use, argument, return, free variable, and control and match flows under implicit flows;
  - code after or beside the sink is excluded;
  - only origins that reach their own rule's sink are run (a spy on `_Run`).
- **Mutation check:** 13 mutants, all caught.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,094 passed, 39 xfailed.
