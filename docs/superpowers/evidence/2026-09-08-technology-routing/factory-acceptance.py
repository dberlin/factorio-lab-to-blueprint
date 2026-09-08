"""Run unchanged original scenario budgets against one frozen source set."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

WORKTREE = Path(__file__).resolve().parents[2]
ROOT = WORKTREE.parents[2]
EVIDENCE = Path(__file__).resolve().parent
OLD = ROOT / '.claude/worktrees/hierarchical-v6/docs/superpowers/evidence/2026-09-08-hierarchical-v6'
PYTHON = str(WORKTREE / '.venv/bin/python')


def source_hashes():
    return {
        str(path.relative_to(WORKTREE)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((WORKTREE / 'src').rglob('*'))
        if path.is_file() and path.suffix in {'.py', '.pyx', '.pyi', '.so'}
    }


def main():
    sources = source_hashes()
    manifest = EVIDENCE / 'factory-source-manifest-r3.json'
    manifest.write_text(json.dumps(sources, indent=2) + '\n')
    cases = []
    for label, original in (
        ('titanium', 'acceptance-titanium-b60-r1-source-r7.json'),
        ('mall-all', 'acceptance-mall-all-b60-r1-source-r7.json'),
        ('mall-none', 'acceptance-mall-none-b60-r1-source-r7.json'),
    ):
        args = json.loads((OLD / original).read_text())['argv']
        cases.append((label, args))
    report = (ROOT / '.superpowers/coater-full9/user-report.txt').read_text()
    match = re.search(r'https://factoriolab\.github\.io/dsp/list\?\S+', report)
    if match is None:
        raise RuntimeError('Exact reported full9 URL missing')
    cases.append(('full9', [match.group(0), '--strategy', 'freeform', '--budget', '60',
                           '--band', 'portable', '--candidate-policy', 'all-products',
                           '--machine-rank', 'up-to', '--workers', '32', '-v']))
    cpus = sorted(os.sched_getaffinity(0))
    slices = [cpus[index::len(cases)] for index in range(len(cases))]

    def run(index_case):
        index, (label, args) = index_case
        prefix = EVIDENCE / ('factory-' + label + '-r3')
        output = prefix.with_suffix('.blueprint.txt')
        output.unlink(missing_ok=True)
        args = list(args)
        if '-o' in args:
            args[args.index('-o') + 1] = str(output)
        else:
            args.extend(('-o', str(output)))
        command = ['taskset', '-c', ','.join(map(str, slices[index])),
                   PYTHON, '-m', 'flab2bp.cli', *args]
        started = time.monotonic()
        timed_out = False
        with prefix.with_suffix('.log').open('w') as log:
            process = subprocess.Popen(command, cwd=WORKTREE, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=145)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code = 124
        result = {'case': label, 'argv': command, 'exit': code,
                  'timeout': timed_out, 'wall_s': time.monotonic() - started,
                  'source_manifest': str(manifest), 'source_unchanged': source_hashes() == sources,
                  'emitted_bytes': output.stat().st_size if output.exists() else 0}
        prefix.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
        return result

    print('READY', flush=True)
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        results = list(pool.map(run, enumerate(cases)))
    (EVIDENCE / 'factory-acceptance-summary-r3.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
