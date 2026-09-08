import json
import os
import sys
from pathlib import Path
from collections import Counter
root=Path(sys.argv[1])
sys.path[:0]=[str(root/'src'),str(root)]
os.environ['FLAB2BP_COATER_NODE']='off'
from scripts import audit
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout.freeform import plan_strips
entry=next(e for e in URL_CORPUS if e.url_id=='universe-matrix')
rows=[]
for spec in audit._specs_for(entry.url):
 strips=plan_strips(spec,strip_len=12)
 row={'label':spec.label,'spec':spec.model_dump(mode='json'),'machines':sum(g.count for g in spec.groups),'strips':len(strips),'strip_types':dict(Counter(type(s).__name__ for s in strips)),'strip_repr':[repr(s) for s in strips]}
 rows.append(row)
 print(spec.label,row['machines'],row['strips'],flush=True)
Path(sys.argv[2]).write_text(json.dumps(rows,indent=2,sort_keys=True))
