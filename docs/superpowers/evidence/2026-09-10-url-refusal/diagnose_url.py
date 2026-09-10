from __future__ import annotations
import argparse, dataclasses, enum, fractions, hashlib, json, os, pathlib, sys, time, traceback
from flab2bp import pipeline
from flab2bp.cli import build_parser, candidate_policies_from_args
from flab2bp.layout.base import NoValidLayout
from flab2bp.web.jobs import Options, run_build
from flab2bp.web.payload import describe

ROOT = pathlib.Path(__file__).resolve().parent
URL = 'https://factoriolab.github.io/dsp/list?z=eJzLt3UyUMu3LdUyNDAw0NIyVMu3TdIyVcu3dYqCUJVwmcykVFsntaLUCtt4tdzcItuCuuK6zLpAtTJbQ0MAnqAUGg__&v=11'

def encode(x):
    if dataclasses.is_dataclass(x): return {f.name:encode(getattr(x,f.name)) for f in dataclasses.fields(x)}
    if hasattr(x,'model_dump'): return x.model_dump(mode='json')
    if isinstance(x,enum.Enum): return x.value
    if isinstance(x,fractions.Fraction): return str(x)
    if isinstance(x,pathlib.Path): return str(x)
    if isinstance(x,dict): return {str(k):encode(v) for k,v in x.items()}
    if isinstance(x,(tuple,list,set,frozenset)): return [encode(v) for v in x]
    return x

def save(path,x): path.write_text(json.dumps(encode(x),indent=2,sort_keys=True)+'\n')

def prepare():
    dest=ROOT/'evidence';dest.mkdir(exist_ok=True)
    data=pipeline.canonicalize_dataset(pipeline.load_vendored())
    request=pipeline.canonicalize_request(pipeline.parse_url(URL))
    specs=pipeline._build_candidates_canonical(data,request,power_tower_item_id=pipeline._resolve_power_tower(None,request))
    parser=build_parser();args=parser.parse_args([URL]); policies=candidate_policies_from_args(parser,args)
    save(dest/'request.json',request);save(dest/'specs.json',specs)
    save(dest/'contract.json',{'source_commit':(ROOT/'SOURCE_COMMIT').read_text().strip(),'url':URL,'python':sys.version,'executable':sys.executable,'cpu_affinity':sorted(os.sched_getaffinity(0)),'cli_defaults':vars(args),'web_defaults':Options(url=URL),'policies':policies,'worker_budget':min(pipeline._available_cpu_count(),pipeline.DEFAULT_WORKER_BUDGET_CAP),'sequence_islands_serial':pipeline.resolve_sequence_islands('best',16,None),'belt_rules':pipeline.belt_rules_for_url(URL,data),'pipeline_file':pipeline.__file__,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*')) if p.is_file() and p.suffix in ('.py','.pyx','.json','.so')}})
    print(json.dumps({'prepared':str(dest),'candidates':[{'label':s.label,'machines':sum(g.count for g in s.groups),'outputs':encode(s.outputs)} for s in specs.candidates]},sort_keys=True),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('surface',choices=('prepare','web','cli'));ap.add_argument('budget',type=float,nargs='?',default=15);a=ap.parse_args()
    if a.surface=='prepare':prepare();return 0
    dest=ROOT/'evidence'/f'{a.surface}-{a.budget:g}s';dest.mkdir(parents=True,exist_ok=True)
    start=time.monotonic();wall=time.time()
    def note(step):
        event={'elapsed_s':time.monotonic()-start,'step':encode(step)}
        with (dest/'progress.jsonl').open('a') as f:f.write(json.dumps(event,sort_keys=True)+'\n')
        print(json.dumps(event,sort_keys=True),flush=True)
    outcome={'source_commit':(ROOT/'SOURCE_COMMIT').read_text().strip(),'command':sys.argv,'cwd':str(ROOT),'surface':a.surface,'budget_s':a.budget,'started_unix_s':wall,'trace_enabled':False}
    try:
        result=run_build(Options(url=URL,budget_s=a.budget),note) if a.surface=='web' else pipeline.build(URL,time_budget_s=a.budget,on_progress=note)
        outcome.update(status='success',result=describe(result,allow_invalid=False))
        for index,attempt in enumerate(result.attempts):
            save(dest/f'attempt-{index}.json',attempt)
    except NoValidLayout as exc:
        outcome.update(status='refused',exception_type=type(exc).__name__,message=str(exc),details=vars(exc))
    except BaseException as exc:
        outcome.update(status='error',exception_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    finally:
        outcome['elapsed_s']=time.monotonic()-start;outcome['finished_unix_s']=time.time();save(dest/'terminal.json',outcome)
    print(json.dumps({'status':outcome['status'],'elapsed_s':outcome['elapsed_s'],'terminal':str(dest/'terminal.json')},sort_keys=True),flush=True)
    return 0 if outcome['status']=='success' else 3 if outcome['status']=='refused' else 2

if __name__=='__main__':raise SystemExit(main())
