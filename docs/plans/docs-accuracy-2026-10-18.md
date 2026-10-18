# Documentation accuracy, 2026-10-18

## Problem
Two documents no longer match the code:
- `docs/plans/extending-languages.md`, step 2, shows an API that does not exist (`Block`, `Edge`, `handles_type`, `handle_if_statement`, `CFGNode(id=self.next_id(), ...)`, `successors.add`). Its limitations section is also out of date:
  - it says C `switch` fall-through is not fully modelled, but it is;
  - it says Python closure and `global`/`nonlocal` flows are not connected (#42), but the free-variable flows connect them;
  - it lists C array subscripts and struct fields as gaps, but they are weak updates of the root name.
- `README.md` "Limitations":
  - it says the analysis is intraprocedural, but there are argument, return and free-variable flows;
  - it says a Python nested function's reads of enclosing variables are not connected, but they are.

## Plan
- Rewrite step 2 with the real pattern, checked by running it in a scratch script:
  - subclass `CFGVisitor`, implement `get_call_sites`, `get_definitions` and `get_uses`;
  - write `visit_<node type>` methods that return a `CFGTraversalResult`;
  - use `create_node`, `cfg.add_edge`, the loop context, and function registration with `FunctionInfo`;
  - explain what `generic_visit` and `postprocess_cfg` do for you.
  
  Link to `docs/architecture.md` §4.2.
- Rewrite the limitations section from what a probe of each claim shows.
- Correct the README's limitations list.

## Not in scope
#86, #70 and the #87 merged run.

## Results
Executive summary: the language extension guide now describes the real visitor API, and its sample visitor is tested. The limitations in the guide and the README now match what the code does; each claim was checked by building a small program.

- **Step 2 of the guide** explains:
  - `visit_<node type>` methods and `generic_visit`;
  - `CFGTraversalResult`, `create_node` and `cfg.add_edge`;
  - the loop and switch context;
  - helper nodes and `postprocess_cfg`;
  - the three methods a visitor must implement, plus `MUTATING_METHODS` and `get_direct_uses`;
  - what a function needs: ENTRY and EXIT nodes, `FunctionInfo` and registration.
  
  It includes a working sample visitor for functions, `while`, `break` and expression statements, using the C grammar. Writing it showed a trap, now in the guide: the data-flow analyses skip the definitions of a node without an AST node, so an ENTRY needs one.
- **`test/test_extending_languages_doc.py`** runs the sample on a small C file. It checks that the graph, node metadata, def-use chains and argument flows equal the C visitor's. Mutation check: 11 mutants of the sample, all caught after the test file gained a loop without `break` and a top-level declaration.
- **Limitations, from probes:**
  - C: `switch` fall-through is modelled. Pointer writes (`p->f = v`, `*q = v`) and calls through function pointers are not. `[[fallthrough]];` is a plain statement. The grammar does not parse statement expressions or computed `goto`.
  - Java: exceptions, arrow `switch` rules, `assert` and `synchronized` are not modelled. Field and array writes define nothing. Lambda calls count as calls of their statement. Free variables are not connected.
  - Python: closures and globals are connected by free-variable flows, which ignore order. The "#42" line is gone.
  - The old "General Architecture Limitations" list repeated these or was vague, so it was folded into the per-language lists.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,109 passed, 39 xfailed.
- **README:** the "Limitations" list no longer says the analysis is intraprocedural or that Python closures are not connected. It now says which writes are weak updates and which are not tracked. It links to the guide's limitations section.
