import json, pathlib, subprocess, time
ROOT=pathlib.Path(__file__).resolve().parent
for surface in ('web','cli'):
    for budget in (15,30,60):
        dest=ROOT/'evidence'/f'{surface}-{budget}s';dest.mkdir(exist_ok=True)
        command=['uv','run','--frozen','python','diagnose_url.py',surface,str(budget)]
        started=time.time();t=time.monotonic()
        with (dest/'stdout.log').open('w') as out,(dest/'stderr.log').open('w') as err:
            run=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err)
        result={'command':command,'cwd':str(ROOT),'started_unix_s':started,'elapsed_s':time.monotonic()-t,'returncode':run.returncode}
        (dest/'process.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'surface':surface,'budget':budget,**result}),flush=True)
