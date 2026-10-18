# Architecture document, 2026-10-18

## Problem
The only architecture description is a short section in `README.md`. It lists "core components" and "analysis capabilities" in a few words each. It predates the query layer, interprocedural flows, control dependence, taint, the stress runner and this month's performance work. A new reader cannot see how a source file becomes a finding, which module does what, or why the algorithms are what they are.

## Plan
- **`docs/architecture.md`**, written as a pyramid. Each level adds detail to the one above, so a reader can stop at any level:
  1. one paragraph: what the project does, and the pipeline from source text to answers;
  2. the layers and packages, with one line each and the main entry point;
  3. one small program followed through every layer, with the real output: CFG, metadata, reaching definitions, def-use chains, interprocedural flows, control dependence, a slice and a taint finding;
  4. the interesting parts in detail, each with the code it describes and, where one is used, the theory behind it:
     - the language registry;
     - CFG construction: the visitor pattern, entry/exit results, join nodes and their removal, loop contexts, calls linked after the walk, node metadata, no recursion;
     - reaching definitions as a monotone data-flow problem, solved with a worklist in reverse postorder;
     - def-use chains, interprocedural flows, control dependence from post-dominators;
     - the query layer: the fact graph, slicing as reachability, shortest and bounded paths;
     - taint: rules, source discovery, sink reach, the worklist over tainted values and path rebuilding, sanitizers, implicit flows and fields;
     - the front ends (CLI, web API, editor);
     - how it is tested: oracles, corpora, property tests, mutation checks.
  
  Sentences are short. Code is quoted from the source, trimmed but not paraphrased.
- **Tested examples.** The Python blocks in the document run in order, in one namespace, and each block's printed output must equal the output block after it. `test/test_architecture_doc.py` follows the pattern of the taint guide's test.
- **`README.md`.** The "Architecture" section becomes a three-line summary that links to the new document.

## Not in scope
`docs/plans/extending-languages.md` describes an older API (`Block`, `Edge`). Updating it is a separate change.

## Results
Executive summary: `docs/architecture.md` (560 lines) explains the project in four levels:
1. one paragraph and a pipeline diagram;
2. a table of the layers with their entry points;
3. one program followed through every layer, with real output;
4. nine detailed parts, with quoted code and the theory behind them.

Its ten Python examples are checked by `test/test_architecture_doc.py`. The README's architecture section is now a short summary that links to the document.

- **Level 3** follows a seven-line program that passes `input()` to `os.system` through a helper. It shows each layer's output:
  - the CFG, including why the `if`'s join node is gone;
  - node metadata;
  - def-use chains;
  - argument and free-variable flows;
  - control dependence;
  - a forward slice;
  - the taint finding with its path.
- **Level 4:**
  - the language registry;
  - CFG construction: the visitor pattern, entry/exit results, join nodes and their removal, loop context stacks, calls linked after the walk, metadata and weak updates, and walks without recursion;
  - reaching definitions: gen/kill, the loop example, and the worklist in reverse postorder, with the theory of monotone frameworks, fixpoints and reverse postorder;
  - flows between functions and context insensitivity;
  - control dependence from post-dominators (Cooper, Harvey and Kennedy);
  - the query layer: cached analyses, the fact graph, slices as reachability, and depth-first against breadth-first search;
  - taint: rules, the three phases (prepare, origins, sink reach), the worklist over values, path rebuilding, taint as reachability, and its options;
  - the front ends;
  - how correctness is kept: unit tests, oracles, the taint corpus, property tests, stress runs, and mutation checks.
- **Accuracy.**
  - The layer claim was checked against the imports: each package imports only from the layers below it.
  - Quoted code names its file, which the test checks exists. Each quote is labelled when it is trimmed or simplified.
  - The examples' outputs were produced by running them, not typed by hand.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,107 passed, 39 xfailed.
- **Noticed, not changed:**
  - `docs/plans/extending-languages.md` describes an older API.
  - The README's "Known limitations" says a nested function's reads of enclosing variables are not connected. The free-variable flows now connect them.
