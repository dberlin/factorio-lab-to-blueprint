import json,os,pathlib,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parent
for budget in (60,15,30):
    dest=ROOT/'evidence'/f'replay-web-{budget}s';dest.mkdir(exist_ok=True)
    command=['uv','run','--frozen','python','capture_replay.py','web',str(budget)]
    env=dict(os.environ,FLAB_DIAGNOSTIC_DEST=str(dest));start=time.monotonic()
    with (dest/'stdout.log').open('w') as out,(dest/'stderr.log').open('w') as err:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=out,stderr=err)
    record={'command':command,'elapsed_s':time.monotonic()-start,'returncode':result.returncode,'capture_env':{'FLAB_DIAGNOSTIC_DEST':str(dest)},'overlap_note':'May overlap serial CLI baselines; 128 CPUs available; at most two 16-worker requests.'}
    (dest/'process.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
