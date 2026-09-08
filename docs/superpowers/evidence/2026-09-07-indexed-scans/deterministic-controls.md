# Deterministic blueprint controls

## Boundary and operating point

These are **preintegration** controls for frozen candidate `1ca2495f6c86f96bf13053dbac6dbb134e57a2ab`, against pinned baseline `2e861af02b6a5062792f8d21fca009b64aee5ab6`, not current master and not the subsequent Buildings delegation.

- Candidate directory: [`final-correctness-VsyHfZ3l/`](final-correctness-VsyHfZ3l/); its `provenance.json`, `controls.json`, `control-exits.json`, logs and complete `*.blueprint.txt` files are the saved evidence.
- Baseline directory: [`../2026-09-07-buildings-index/parallel-correctness-AWM9wmPE/before/`](../2026-09-07-buildings-index/parallel-correctness-AWM9wmPE/before/). Reused at the matching operating point; not regenerated for this report. Its original worktree has been removed after integration; the committed evidence remains.
- Twelve shipped CLI URLs, `freeform`, `--workers 1`, **budget 60**, default policies, fixed `dotnet_ticks=0`. This differs from the brief's budget-30 recipe and is not evidence for that unrun exact recipe. Actual URLs are preserved in `controls.json`; the CLI accepts a positional URL, not the brief's invalid `--url-id` flag. Audit strategy `both` is valid; the CLI equivalent is `best`.
- The report directly compared **all bytes** of each saved file, without normalization, decoding, truncation or sampling. Both original `control-exits.json` files contain exactly these twelve entries, all exit 0. Byte equality, not equal length or a hash prefix, decides MATCH below.

## Original paired controls: 11 MATCH, 1 DIFFERS

| URL ID | Baseline bytes | Candidate bytes | Complete-byte result |
|---|---:|---:|---|
| iron-ingot | 527 | 527 | MATCH |
| magnetic-coil | 1255 | 1255 | MATCH |
| graphene | 1590 | 1590 | MATCH |
| electromagnetic-matrix | 4262 | 4262 | MATCH |
| plastic | 3473 | 3473 | MATCH |
| processor | 5120 | 5120 | MATCH |
| energy-matrix | 3441 | 3441 | MATCH |
| super-magnetic-ring | 20939 | 20939 | MATCH |
| casimir-crystal | 7585 | 7585 | MATCH |
| information-matrix | 37446 | 37446 | MATCH |
| quantum-chip | 39312 | 36156 | **DIFFERS** |
| universe-matrix | 149455 | 149455 | MATCH |

Original quantum-chip SHA-256:

- Baseline: `605d6d7e2bd1ce149b1ba1c39caa101b2dc3e185eb50c9be115982381e226a49`
- Candidate: `7454a4e349b367af3cf5a01134c6e9415f39184a88e3d1cfbc2ad617c4c93b6b`

**The original strict all-twelve byte-identity result is FAIL.** The original mismatch is preserved; the later pair does not overwrite or retroactively relabel it.

## Separate serial quantum-chip check: MATCH

Saved under [`final-correctness-VsyHfZ3l/serial-quantum-chip/`](final-correctness-VsyHfZ3l/serial-quantum-chip/):

| Side | Log exit | Complete file bytes | SHA-256 |
|---|---:|---:|---|
| baseline | 0 | 36156 | `7454a4e349b367af3cf5a01134c6e9415f39184a88e3d1cfbc2ad617c4c93b6b` |
| candidate | 0 | 36156 | `7454a4e349b367af3cf5a01134c6e9415f39184a88e3d1cfbc2ad617c4c93b6b` |

The serial files are fully byte-identical to each other and to the original candidate; they are **not** identical to the original baseline. Both serial logs report freeform/all-products, 49 machines, 3825 tiles and 2637 buildings. This provides a successful serial comparison for the previously differing cell, not a new twelve-cell serial run and not unique causal attribution of the original mismatch.

The last five runnable-process samples in `baseline-load.txt` are 11/16/14/19/9 and in `candidate-load.txt` are 8/26/8/6/21: both means **13.8**. The first cumulative vmstat sample is excluded. No serial process-wall ratio is saved here, and none is invented.

## Interpretation

The original eleven matching pairs plus the separate matching serial quantum-chip pair supply matching complete outputs for every named URL, under the recorded controls. They do not establish that every wall-bounded execution is byte-identical. The original mismatch and twelve named corpus area changes remain in the [main report](README.md). The user's later retention ruling removes marginal timing-based keep/revert queues, not the duty to report differences or actual correctness/deadline failures.

This document's original controls are saved preintegration evidence, not final combined proof. The constructor/Sorters delegation subsequently landed at `916ea738`; [the main report, §11](README.md#11-final-combined-source-and-failure-only-serial-adjudication) records the separate final comparison against `f863ee79`: eleven successful complete-byte controls match; universe-matrix refuses on both sides and still refuses in the failure-only serial pair. The final coverage/output gates remain FAIL.
