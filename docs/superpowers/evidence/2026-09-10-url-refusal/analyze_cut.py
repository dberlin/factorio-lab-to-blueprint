import collections,json,pathlib,pickle,time
from fractions import Fraction
from flab2bp.layout import validate
import networkx as nx
from flab2bp.dsp import catalog
from diagnose_url import encode
ROOT=pathlib.Path(__file__).resolve().parent
model=pickle.loads((ROOT/'evidence'/'hydrogen-physical-model.pickle').read_bytes())
args,kwargs,report=pickle.loads((ROOT/'evidence'/'hydrogen-freeform-30s'/'certifications.pickle').read_bytes())[0]
bs=args[0].buildings
labels=collections.defaultdict(list)
for r in model.resources:
    for i in r.arcs:
        arc=model.arcs[i]
        if arc.item!='hydrogen':continue
        if r.kind=='sorter':
            s=bs[r.buildings[0]]
            if s.input_obj is not None and not catalog.is_belt(bs[s.input_obj].item_id):labels[arc.source].append(('producer',s.input_obj))
            if s.output_obj is not None and not catalog.is_belt(bs[s.output_obj].item_id):labels[arc.sink].append(('consumer',s.output_obj))
        else:
            labels[arc.source].append(('belt-in',r.buildings))
            labels[arc.sink].append(('belt-out',r.buildings))
G=nx.DiGraph();balances=collections.defaultdict(Fraction);source=model.nodes;sink=source+1
arcs=[]
for i,a in enumerate(model.arcs):
    if a.item!='hydrogen':continue
    balances[a.source]-=a.lower;balances[a.sink]+=a.lower
    if a.capacity>a.lower:arcs.append((a.source,a.sink,a.capacity-a.lower,i))
for n,b in balances.items():
    if b>0:arcs.append((source,n,b,-1))
    elif b<0:arcs.append((n,sink,-b,-1))
for a,b,c,i in arcs:
    if G.has_edge(a,b):G[a][b]['capacity']+=c
    else:G.add_edge(a,b,capacity=c)
value,(left,right)=nx.minimum_cut(G,source,sink)
cut=[{'source':a,'sink':b,'capacity':str(c),'arc_index':i,'source_labels':labels[a],'sink_labels':labels[b]} for a,b,c,i in arcs if a in left and b in right]
obligations=[{'node':n,'balance':str(b),'labels':labels[n],'source_side':n in left} for n,b in balances.items() if b]
result={'mincut':str(value),'cut':cut,'obligations':obligations,'model_nodes':model.nodes,'hydrogen_arcs':len(arcs)}
(ROOT/'evidence'/'hydrogen-mincut.json').write_text(json.dumps(result,indent=2,default=repr)+'\n')
print(json.dumps(result,default=repr))
