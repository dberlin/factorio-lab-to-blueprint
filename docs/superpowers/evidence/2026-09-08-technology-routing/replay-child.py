"""Replay a trusted production child, rebasing only its recorded monotonic clock."""
import argparse
import cProfile
import json
from pathlib import Path
import pickle
import time
import traceback

from flab2bp.layout.base import NoValidLayout

parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--profile', action='store_true')
options = parser.parse_args()
with options.input.open('rb') as stream:
    solver, args, kwargs = pickle.load(stream)
profiler = cProfile.Profile() if options.profile else None
started = time.monotonic()
result: dict[str, str | bool | int | float] = {
    'input': str(options.input), 'positional_options': repr(args[1:]),
    'keyword_options': repr(kwargs), 'arguments_modified': False,
}
if kwargs.get('absolute_deadline') is not None:
    captured_start = int(options.input.stem.rsplit('-', 1)[1]) / 1_000_000_000
    remaining = kwargs['absolute_deadline'] - captured_start
    kwargs['absolute_deadline'] = started + remaining
    result.update(arguments_modified=True, absolute_deadline_rebased=True,
                  original_remaining_seconds=remaining,
                  replay_keyword_options=repr(kwargs))
try:
    if profiler is None:
        placement = solver.lay_out(*args, **kwargs)
    else:
        placement = profiler.runcall(solver.lay_out, *args, **kwargs)
    result.update(status='PLACED', buildings=len(placement.buildings), exit=0)
except NoValidLayout as error:
    result.update(status='REFUSED', message=str(error), exit=3)
except Exception:
    result.update(status='ERROR', traceback=traceback.format_exc(), exit=1)
finally:
    result['wall_s'] = time.monotonic() - started
    if profiler is not None:
        profiler.dump_stats(str(options.output.with_suffix('.pstats')))
    options.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
raise SystemExit(result['exit'])
