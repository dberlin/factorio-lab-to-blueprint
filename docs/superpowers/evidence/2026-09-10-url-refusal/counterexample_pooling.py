import json,pathlib,time
from fractions import Fraction as F
import networkx as nx
from flab2bp.layout.routing_domain import _join_shard_islands
start=time.monotonic()
pairs=[(10,30),(20,30),(20,40)]
supply={10:F(5),20:F(5)};demand={30:F(1),40:F(9)}
extra=_join_shard_islands(pairs,supply,demand,F(0))
g=nx.DiGraph()
for a,b in pairs+extra:g.add_edge(a,b,capacity=F(10))
for n,rate in supply.items():g.add_edge('source',n,capacity=rate)
for n,rate in demand.items():g.add_edge(n,'sink',capacity=rate)
maximum=nx.maximum_flow_value(g,'source','sink')
result={'pairs':pairs,'supply':{k:str(v) for k,v in supply.items()},'demand':{k:str(v) for k,v in demand.items()},'returned_extra':extra,'maximum_directed_flow':str(maximum),'required':'10','shortfall':str(F(10)-maximum),'elapsed_s':time.monotonic()-start}
p=pathlib.Path(__file__).parent/'evidence'/'minimal-pooling-counterexample.json';p.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
