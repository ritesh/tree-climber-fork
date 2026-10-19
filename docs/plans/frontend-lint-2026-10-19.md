# Frontend lint (#29), 2026-10-19

## Problem
`bun run lint` in `src/tree_climber/viz/frontend` reports 18 errors and 7 warnings, so CI only builds the frontend and does not lint it.

## Plan
- Replace each `any` with a real type: the Monaco editor and model types, Cytoscape's types, and small local types for the `cytoscape-node-html-label` stub and the dagre layout options.
- Fix `prefer-const` and the two unused names.
- Warnings:
  - `react-hooks/exhaustive-deps` in `App.tsx`: fix the effect's dependencies without changing when it runs.
  - `react-refresh/only-export-components` in `GraphContext.tsx` and `LanguageSelector.tsx`: move the hook and constants they export into their own module, so the component files export only components.
- CI: the `Frontend build` job also runs `bun run lint`.
- Behaviour must not change. `bun run build` (which type-checks) must pass, and the editor should be tried in a browser: parse, the graph, selecting nodes, taint findings.

## Results
Executive summary: `bun run lint` now exits 0 with no errors or warnings, and CI's `Frontend build` job runs it before the build. Every `any` has a real type. The app behaves as before in a browser, except that it no longer parses the code twice on startup.

- **Types:**
  - Monaco: the editor ref, the decorations collection and `onMount` use Monaco's editor types.
  - Cytoscape: elements are `ElementDefinition[]`, and the dagre options are `DagreLayoutOptions`, so the layout call needs no cast.
  - `cytoscape-node-html-label`: the module takes `typeof cytoscape`, and a label template gets the node's data. The augmentation file is a module through `export {}` instead of an unused import.
  - `getNodeAttribute` returns the attribute's own type.
  - Typing the editor found one real gap: the selection handler used the model without checking it for null. It now returns early, as the cursor handler beside it does.
- **Fast refresh:** `GraphContext.tsx` now exports only `GraphProvider`. The context, `useGraph`, the types and the node-selection callbacks moved to `graphState.ts`. `loadLanguage` (and a new `saveLanguage`) moved to `sampleCode.ts`, next to the per-language code storage.
- **`App.tsx` hook dependencies:** the effect that re-parsed on a language change did the same work as the editor's own effect, which already sends the new language's code. It is removed, with the `isInitialized` state that only it used. `handleCodeChange` is a `useCallback` on `language`, so the editor's effect no longer re-runs when unrelated App state changes.
- **Browser check** (Playwright, this branch against master, same steps):
  - the graph, findings, path highlighting, cursor-to-node and node-to-editor selection, language switching and editing all match;
  - neither has console errors;
  - startup requests: master sends `/taint` and `/parse` twice, this branch once.
  
  Noticed on both: after switching from Python to Java, the graph panel can look empty until "Reset Zoom", apparently because the saved zoom and pan are reused for the new graph. Not changed here.
- **Checks:** `bun run lint` is clean and `bun run build` passes (type-check included).
