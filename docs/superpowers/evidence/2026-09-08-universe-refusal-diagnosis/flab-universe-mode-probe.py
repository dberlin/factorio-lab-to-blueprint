import argparse
import json
import os
from pathlib import Path
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('off', 'placed'), required=True)
    parser.add_argument('--workers', type=int, required=True)
    parser.add_argument('--strategy', choices=('freeform', 'sequence-pair'), required=True)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.environ['FLAB2BP_COATER_NODE'] = args.mode

    import sys
    sys.path.insert(0, str(Path.cwd()))
    from scripts import audit
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES
    from flab2bp.layout.coater_mode import coater_mode

    entry = next(entry for entry in URL_CORPUS if entry.url_id == 'universe-matrix')
    policies = DEFAULT_CANDIDATE_POLICIES
    spec_index = next(i for i, policy in enumerate(policies) if policy.value == args.policy)
    job = audit.Job(strategy=args.strategy, url_id=entry.url_id, url=entry.url,
                    tier=entry.tier.value, spec_index=spec_index,
                    candidate_policies=policies, budget=30.0, workers=args.workers)
    audit._COMMIT = 'bbc8889d'
    started = time.monotonic()
    result = audit.run_cell(job)
    audit.record({args.strategy: audit.Tally()}, result)
    row = audit._JSONL[-1]
    row.update(probe_workers=args.workers, probe_affinity=sorted(os.sched_getaffinity(0)),
               probe_mode=coater_mode().value, probe_elapsed_s=time.monotonic()-started,
               probe_url=entry.url)
    args.output.write_text(json.dumps(row, indent=2))
    print(args.mode, args.workers, args.strategy, args.policy, result.status,
          result.area, result.detail, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
