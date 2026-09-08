"""Diagnostic only: profile unchanged production child calls, including spawn workers."""
import cProfile
import json
import os
from pathlib import Path
import pickle
import time

from flab2bp.layout.freeform import FreeformLayout
from flab2bp.spec import BuildSpec

EVIDENCE = Path(__file__).resolve().parent
WORKTREE = EVIDENCE.parents[1]
ROOT = WORKTREE.parents[2]
ORIGINAL = FreeformLayout.lay_out


def profiled(self, *args, **kwargs):
    profile = cProfile.Profile()
    started = time.monotonic()
    prefix = EVIDENCE / f'child-profile-{os.getpid()}-{time.monotonic_ns()}'
    spec = args[0] if args else kwargs.get('spec')
    if isinstance(spec, BuildSpec):
        prefix.with_suffix('.spec.json').write_text(spec.model_dump_json(indent=2))
        with prefix.with_suffix('.pickle').open('wb') as stream:
            pickle.dump((self, args, kwargs), stream, protocol=pickle.HIGHEST_PROTOCOL)
    try:
        return profile.runcall(ORIGINAL, self, *args, **kwargs)
    finally:
        profile.dump_stats(str(prefix.with_suffix('.pstats')))
        prefix.with_suffix('.timing.json').write_text(json.dumps({
            'wall_s': time.monotonic() - started, 'scope': 'profiled child, not acceptance',
        }))


FreeformLayout.lay_out = profiled

if __name__ == '__main__':
    from flab2bp.cli import main
    old = ROOT / '.claude/worktrees/hierarchical-v6/docs/superpowers/evidence/2026-09-08-hierarchical-v6'
    args = json.loads((old / 'acceptance-titanium-b60-r1-source-r7.json').read_text())['argv']
    args[args.index('-o') + 1] = str(EVIDENCE / 'titanium-profile-diagnostic.blueprint.txt')
    print('READY', flush=True)
    raise SystemExit(main(args))
