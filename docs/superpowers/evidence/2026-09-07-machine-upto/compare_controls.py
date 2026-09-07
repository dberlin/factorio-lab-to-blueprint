"""Compare all twelve complete blueprint digests; refusals cannot prove identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_gate import URL_IDS, read_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    arms = {}
    for arm in ("base", "exact"):
        rows = read_rows(args.directory / f"controls-{arm}.jsonl")
        arms[arm] = {row["url_id"]: row for row in rows}
        if len(rows) != 12 or set(arms[arm]) != set(URL_IDS):
            raise RuntimeError(f"{arm}: expected twelve unique control URLs")
    failed = False
    for url_id in URL_IDS:
        before, after = (arms[arm][url_id] for arm in ("base", "exact"))
        valid = all(row.get("status") == "CLEAN" and row.get("digest")
                    and row.get("workers") == 1 and row.get("policy") == "no-proliferator"
                    and row.get("strategy") == "freeform" for row in (before, after))
        passed = bool(valid and before["digest"] == after["digest"])
        failed |= not passed
        print(json.dumps({"url_id": url_id, "pass": passed,
                          "base_status": before.get("status"),
                          "exact_status": after.get("status"),
                          "reason": "matching full blueprint" if passed else
                          "missing clean digest or blueprint mismatch"}, sort_keys=True))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
