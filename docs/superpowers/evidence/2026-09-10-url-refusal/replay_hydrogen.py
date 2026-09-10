import json,pathlib,pickle,time
from flab2bp import pipeline
from flab2bp.layout import finalize
from flab2bp.layout.base import NoValidLayout
from flab2bp.rates.candidates import CandidatePolicy
from diagnose_url import URL,encode
ROOT=pathlib.Path(__file__).resolve().parent
DEST=ROOT/'evidence'/'hydrogen-freeform-30s';DEST.mkdir(exist_ok=True)
ORIGINAL=finalize._certify
RECORDS=[]
def record(*args,**kwargs):
    result=ORIGINAL(*args,**kwargs)
    if result.errors:RECORDS.append((args,kwargs,result))
    return result
finalize._certify=record
if __name__=='__main__':
    start=time.monotonic()
    try:
        result=pipeline.build(URL,strategy='freeform',candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),time_budget_s=30)
        outcome={'status':'success'}
    except NoValidLayout as exc:
        outcome={'status':'refused','reason':str(exc),'details':encode(vars(exc))}
    except Exception as exc:
        outcome={'status':'error','reason':repr(exc)}
    outcome['elapsed_s']=time.monotonic()-start
    (DEST/'terminal.json').write_text(json.dumps(outcome,indent=2)+'\n')
    (DEST/'certifications.pickle').write_bytes(pickle.dumps(RECORDS))
    print(json.dumps({'status':outcome['status'],'elapsed_s':outcome['elapsed_s'],'certifications':len(RECORDS)}))
