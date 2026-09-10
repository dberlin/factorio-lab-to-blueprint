import collections,json,pathlib,pickle
from flab2bp.layout import validate,markers
from flab2bp.dsp import catalog
from diagnose_url import encode
ROOT=pathlib.Path(__file__).resolve().parent
paths=[ROOT/'evidence'/'hydrogen-freeform-30s'/'certifications.pickle']
for path in paths:
    records=pickle.loads(path.read_bytes()); print(path.name,'records',len(records))
    summaries=[]
    for args,kwargs,report in records:
        placement,spec=args[:2];bs=placement.buildings
        print('certification args',len(args),kwargs,'errors',[(f.check,f.message) for f in report.errors])
        rules=kwargs['belt_rules']
        ctx=validate._context(placement,spec,validate.id_map(spec),10000,rules.max_z,rules.vertical_construction)
        recipe=catalog.recipe_id('x-ray-cracking');machines=[i for i,b in enumerate(bs) if b.recipe_id==recipe]
        ins=[i for i,b in enumerate(bs) if b.output_obj in machines and catalog.is_sorter(b.item_id) and b.carries_item=='hydrogen']
        outs=[i for i,b in enumerate(bs) if b.input_obj in machines and catalog.is_sorter(b.item_id) and b.carries_item=='hydrogen']
        taps={bs[i].input_obj for i in ins}; roots={bs[i].output_obj for i in outs}
        links=[]
        for start in roots:
            seen=set();q=collections.deque([start]);found=False
            while q:
                i=q.popleft()
                if i is None or i in seen:continue
                seen.add(i)
                if i in taps:found=True;break
                b=bs[i]
                q.extend(ctx.buildings_index.transport_successors(i))
                q.extend(bs[j].output_obj for j in ctx.sorters().drawing_from_carrying(i,'hydrogen'))
            links.append({'root':start,'reachable_taps':found,'visited':sorted(seen),'chain_end':encode(bs[max(seen)]) if seen else None})
        relevant=sorted(set(machines+ins+outs+list(taps)+list(roots)))
        summary={'errors':encode(report.errors),'machines':machines,'input_sorters':ins,'output_sorters':outs,'prime_heads':markers.self_loop_prime_heads(placement,spec),'hydrogen_paths':links,'buildings':{i:encode(bs[i]) for i in relevant},'spec':spec.model_dump(mode='json')}
        summary['physical_hydrogen_result']=encode(validate._solve_physical(ctx,items=frozenset({'hydrogen'})))
        snapshot=validate._physical_flow(ctx)
        (ROOT/'evidence'/'hydrogen-physical-model.pickle').write_bytes(pickle.dumps(snapshot.model))
        summaries.append(summary)
        print('hydrogen',json.dumps({k:v for k,v in summary.items() if k not in ('buildings','spec','errors')}))
    (ROOT/'evidence'/'hydrogen-rejected-analysis.json').write_text(json.dumps(summaries,indent=2,default=repr)+'\n')
