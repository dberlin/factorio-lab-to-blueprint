import json,pathlib,pickle,time
from fractions import Fraction
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
from flab2bp import pipeline
from flab2bp.spec import BuildSpecSet
from diagnose_url import URL,encode
ROOT=pathlib.Path(__file__).resolve().parent
rows=[];original=rd._join_shard_islands

def capture(pairs,supply,demand,external):
    result=original(pairs,supply,demand,external)
    rows.append({'pairs':pairs,'supply':supply,'demand':demand,'external':external,'result':result})
    return result

if __name__=='__main__':
    path=next((ROOT/'evidence'/'replay-v2-web-60s').glob('freeform-no-proliferator-*.pickle'))
    saved=pickle.loads(path.read_bytes());a=saved['attempts'][0]
    spec=next(s for s in BuildSpecSet.model_validate_json((ROOT/'evidence'/'specs.json').read_text()).candidates if s.label=='no-proliferator')
    pack=rd._Pack(at=dict(enumerate(a.origins)),width=a.compact_width,height=a.height,status='replay-original')
    rd._join_shard_islands=capture
    t=time.monotonic()
    prepared=rd._prepare_routing_problem(spec,saved['strips'],pack,power=True,policy=BandPolicy('portable'),_reserve_ports=True,belt_rules=pipeline.belt_rules_for_url(URL,pipeline.load_vendored()),deadline=time.monotonic()+15)
    result={'elapsed_s':time.monotonic()-t,'source':str(path),'original_first_pack':{'width':a.compact_width,'height':a.height},'calls':rows}
    (ROOT/'evidence'/'shard-pooling-calls.json').write_text(json.dumps(encode(result),indent=2,default=repr)+'\n')
    print('calls',len(rows),'elapsed_s',result['elapsed_s'])
    for row in rows:
        if row['external']==Fraction(727,48):print('HYDROGEN',json.dumps(encode(row)))
