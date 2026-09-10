"""Read-only capture of existing coarse search-boundary records; no profiling."""
import collections, dataclasses, json, os, pathlib, pickle, sys, time
import diagnose_url as diagnosis
from flab2bp.layout import freeform, sequence_solver, sequence_islands
import copyreg
from types import MappingProxyType
copyreg.pickle(type(MappingProxyType({})), lambda value: (dict, (dict(value),)))

DEST=pathlib.Path(os.environ['FLAB_DIAGNOSTIC_DEST']);DEST.mkdir(parents=True,exist_ok=True)
RUNS={}
ORIGINAL_PRODUCTION=sequence_solver._production_run
ORIGINAL_SEARCH=sequence_solver.SequenceSolver.search
ORIGINAL_SWEEP=freeform.FreeformLayout._sweep
from flab2bp.layout import validate
ORIGINAL_CERTIFY=validate.certify
CERTIFIED=[]

def certify(*args,**kwargs):
    report=ORIGINAL_CERTIFY(*args,**kwargs)
    if not report.ok:
        CERTIFIED.append((args,kwargs,report))
    return report

def snapshot(name, value):
    p=DEST/f'{name}-{os.getpid()}'
    try:
        p.with_suffix('.pickle').write_bytes(pickle.dumps(value))
    except Exception as exc:
        p.with_suffix('.capture-error').write_text(repr(exc)+'\n')

def production(*args,**kwargs):
    run=ORIGINAL_PRODUCTION(*args,**kwargs)
    RUNS[id(run.solver)]=(run,args[0].label,kwargs.get('compact_seed_attempt'),kwargs.get('compact_seed_base_seed'))
    return run

def search(self,*args,**kwargs):
    try:return ORIGINAL_SEARCH(self,*args,**kwargs)
    finally:
        if id(self) in RUNS:
            run,label,attempt,seed=RUNS.pop(id(self))
            payload={'label':label,'compact_seed_attempt':attempt,'compact_seed_base_seed':seed,'telemetry':dataclasses.asdict(run.telemetry),'stats':sequence_solver._refusal_stats(run),'heights':run.heights,'stages':tuple(self._stage_stats)}
            snapshot('sequence-'+label,payload)
            (DEST/f'sequence-{label}-{os.getpid()}.json').write_text(json.dumps(diagnosis.encode(payload),indent=2,default=repr)+'\n')

def sweep(self,*args,**kwargs):
    try:return ORIGINAL_SWEEP(self,*args,**kwargs)
    finally:
        spec,strips=args[:2]; attempts=args[6] if len(args)>6 else kwargs.get('attempts',[])
        payload={'label':spec.label,'strips':strips,'attempts':attempts,'rejected':args[5] if len(args)>5 else kwargs.get('rejected',[]),'telemetry':kwargs.get('telemetry'),'skipped_heights':kwargs.get('skipped_heights')}
        snapshot('certification-'+spec.label,tuple(CERTIFIED))
        CERTIFIED.clear()
        snapshot('freeform-'+spec.label,payload)
        summary={'label':spec.label,'telemetry':payload['telemetry'],'rejected':diagnosis.encode(payload['rejected']),'skipped_heights':payload['skipped_heights'],'attempts':[{'height':a.height,'width':a.compact_width,'budget_stage':None if a.budget_stage is None else a.budget_stage.value,'failure_kinds':dict(collections.Counter(f.kind.value for f in a.routing.failures)),'routing':diagnosis.encode(a.routing)} for a in attempts]}
        (DEST/f'freeform-{spec.label}-{os.getpid()}.json').write_text(json.dumps(summary,indent=2,default=repr)+'\n')

sequence_solver._production_run=production
sequence_islands._production_run=production
sequence_solver.SequenceSolver.search=search
freeform.FreeformLayout._sweep=sweep
validate.certify=certify

if __name__=='__main__':
    # Reuse unchanged public request construction, but own a separate evidence tree.
    diagnosis.ROOT=DEST
    (DEST/'SOURCE_COMMIT').write_text((pathlib.Path(__file__).parent/'SOURCE_COMMIT').read_text())
    raise SystemExit(diagnosis.main())
