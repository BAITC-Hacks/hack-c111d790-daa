"""Evaluate the imported reports; output contains source-derived metrics, no synthetic business inputs."""

import json
from pathlib import Path

from backend.partner_api import calculate_company
from backend.partner_models import PartnerCalculate
from backend.partner_store import companies


def main():
    result = {}
    for company in companies():
        run = calculate_company(company["id"], PartnerCalculate(limit=4000))
        result[company["id"]] = {k: run[k] for k in ["id", "model_version", "summary", "evaluation_scope"]}
        print(json.dumps({company["id"]: result[company["id"]]}, ensure_ascii=False), flush=True)
    target = Path("data/partners/benchmark.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
