import json

def cells(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("url_id") == "universe-matrix":
            out[(r["strategy"], r["spec_index"], r["spec_label"])] = (
                r.get("status"), r.get("area")
            )
    return out

base = cells("/tmp/broke6-baseline-1.jsonl")
print("baseline-1 universe-matrix cells:", len(base))
for round in (1, 2, 3):
    cand = cells(f"/tmp/broke6-candidate-{round}.jsonl")
    for key in sorted(set(base) | set(cand)):
        b = base.get(key)
        c = cand.get(key)
        moved = "" if b == c else "  <<< MOVED"
        print(round, key, "base", b, "cand", c, moved)
