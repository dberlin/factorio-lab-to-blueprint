# General abstraction repairs: integrated acceptance

## Result and integration

All sixteen selected general tasks are implemented and reviewed. Source is merged on master `2523c92d`; no push was performed. The separate original repairs were merged at `e6e35609`, and hierarchy v5 at `95dcc843`. General's final source commit is `9d32ec99`.

This is contract acceptance, not a claim that every factory or the full Python suite passes. Existing Universe, cold all-products, Substation and large hierarchy target refusals remain documented failures. Hierarchical v6 is separate, active and not merge-ready.

## Merge preservation proof

Seven conflicted files were restored from the verified general branch. This resolution was audited against both parents after the user requested explicit equivalence proof; future whole-file resolutions must perform this check first.

- Every one of those seven pre-merge master blobs equals the corresponding blob at general prerequisite `f1b22604`, including file mode. General `9d32ec99` descends from that prerequisite. No master-only edits existed in those seven files.
- All six original source/contract commits and the v5 repair have patch-equivalent copies in general.
- An independent temporary Git index started from pre-merge master `95dcc843` and applied the four early general commits. Its complete source/test/tool/web/dependency tree equals `f1b22604`. This accounts for the other fourteen differing master-side files as intentional general changes, not lost edits.
- The merged source, tests, scripts, web and dependency files equal the reviewed general source exactly. Every pre-merge master documentation file is preserved exactly, including the original repair evidence absent from general.
- Five pre-existing untracked planning/evidence documents that blocked the first merge were preserved under `/home/dannyb/sources/flab-worktree-archives/2026-09-08/root-preintegration-documents/`. Three were identical to incoming files; the incoming original findings/plan contained newer completion evidence.

Full blob identities and reconstruction commands/results: [merge-preservation-audit.json](merge-preservation-audit.json).

## Fresh merged-master verification

All commands below executed against merged master, not merely the feature worktree. Exact commands, exits and elapsed times are retained in [master-gates.json](master-gates.json).

| Gate | Observed result |
|---|---|
| Ruff, `src tests scripts` | EXIT0 |
| mypy, `src` | EXIT0; 106 source files |
| Composition/finalization/indexed/CLI-strategy consumers plus five focused completion regressions | EXIT0; 280 cases |
| Web typecheck | EXIT0 |
| Web lint/format check | EXIT0 |
| Complete web test command | EXIT0; 39 files, 409 cases |
| Production web build | EXIT0 |
| Actual CLI: Freeform, SequencePair and hierarchy × restricted/unrestricted save | Six EXIT0; each emitted and decoded 14 buildings with valid checksum |

CLI commands, output hashes and decode results: [master-cli-acceptance.json](master-cli-acceptance.json). The restricted URL uses `tre=B`, with altitude ceiling8.55 and no vertical belt construction. The unrestricted URL assumes full research, ceiling26.55 and vertical construction. Separate same-placement judgment probes establish that forbidden altitude/vertical transitions are actually rejected; the small CLI fixtures do not need those transitions.

An earlier feature-worktree CLI batch mistakenly supplied `--sequence-islands` to Freeform/hierarchy. Those four commands correctly refused their arguments; corrected commands passed. The failed command records are retained and are not layout failures.

## Causal proof and functional payoff

Detailed source ownership, causal observations and limitations are retained in the fifteen `task-*-report.md` files.

- Request boundary preserves explicit zero and resolves external-input authorization once. Physical machine area comes from canonical DSP identity rather than ambient name lookup.
- Production-equivalent judgments carry the same researched save policy. Audit identity preserves distinct numeric budgets and rejects duplicates; one job owner settles interrupted execution and closes native resources without losing completed peer results.
- Sampled traces remap retained endpoints and remove omitted endpoints rather than manufacturing links. The actual browser displayed the 3,001-building sampled frame. After the job was terminal, an empty poll remained incomplete while collector final drain was held. Releasing the drain delivered the second real frame; only the subsequent empty poll reported complete.
- Atomic document publication keeps imported, traced and completed artifacts distinct. Nine browser transitions, exact per-attempt instructions and non-square Oil Refinery framing/selection were verified. In the actual solver Stop-watching scenario, the browser detached while the job was running; the server completed all six attempts in17.55s. A newer imported blueprint remained displayed, with no late build report, trace or copy controls leaking back.
- Shared routing mechanisms have one strategy-neutral owner. All234 moved declarations were AST-identical to the reconciled source, and four prepared routing replays preserved outcomes, isolation and construction/copy counts. No speedup is claimed.
- Completion has one concrete two-stage owner without absorbing strategy ranking. All27 clock cases preserve Freeform/SequencePair's five-second grace and hierarchy's distinct projection/acceptance policy. Changed projection discards a cached cleanup Report. Real invalid demand and projection refusal remain failures. The measured Freeform gate skipped five certifications among nine projected candidates; no redundant-certification saving is claimed beyond observed skips.
- Composition uses the existing selected-band envelope within the unchanged candidate domain. The mixed witness changes rejected80×106 to244×42, routes3/3 and passes final judgment. The rotated control remains valid and801×20 overflow still refuses. A fitting pre-route outline does not guarantee later routed/power geometry fits.

## Review and limits

Scoped completion and band reviews plus final integrated review found no actionable patch-introduced defects. See [completion-review.json](completion-review.json), [band-review.json](band-review.json) and [integrated-review.json](integrated-review.json). Reviews were read-only source/evidence audits; they did not independently execute tests. LSP failures required grounded source/AST callsite audits.

Earlier broad Python routing/module commands exceeded the150-second bound. They are not counted as passing suites. The inherited cold all-products refusal was reproduced on unchanged master; one obsolete wording assertion was deleted and one moved test interception was corrected with focused proof. No broad Python-suite PASS, general factory-reliability gain, Windows acceptance, or change to deferred machine-override/nested-alias semantics is claimed.

## Evidence retention

[retained-artifacts.json](retained-artifacts.json) records selected feature-worktree evidence hashes. Fresh master evidence was added afterward. Full scratch scripts, specimens and unpromoted experiments are preserved in retirement archives outside the repository; they are not new production APIs or permanent tests. Worktree removal does not promote archived experiment code. The protected `plan-feasibility-first` worktree is excluded from retirement.

All nine stale worktrees were removed only after independent archive/source hash verification of42,680 regular files. Branches remain intact. The final registry contains only master, active hierarchical-v6 and protected plan-feasibility-first. V6's immutable v5 source/evidence inputs were relocated outside Git worktrees; all120 source/dependency hashes and an actual owner replay agree. See [worktree-retirement.json](worktree-retirement.json) and [relocated-v5-baseline.json](relocated-v5-baseline.json).
