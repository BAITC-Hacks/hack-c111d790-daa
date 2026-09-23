"""Reproducible synthetic benchmark, without writing to the application database."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from backend.demo import make_demo
from backend.forecasting import MODEL_VERSION
from backend.planning import calculate
from backend.schemas import CalculateRequest, Dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/benchmark.json"))
    args = parser.parse_args()
    data = Dataset.model_validate_json(args.input.read_text()) if args.input else make_demo()
    started = perf_counter()
    result = calculate(data, CalculateRequest())
    report = {
        "dataset": data.name,
        "synthetic": data.synthetic,
        "seed": 42 if not args.input else None,
        "as_of": str(data.as_of),
        "model_version": MODEL_VERSION,
        "elapsed_seconds": round(perf_counter() - started, 3),
        "summary": result["summary"],
        "method": "Two 28-day tuning folds, separate last-28-day holdout; available days only; value-weighted and macro WAPE.",
        "limitations": "Synthetic data. No measured business savings. Intervals and safety stock are approximate.",
        "positions": [
            {
                k: row[k]
                for k in [
                    "sku",
                    "warehouse",
                    "model",
                    "evaluation",
                    "baseline",
                    "quantity",
                    "excluded_units",
                    "lost_units",
                    "stockout_days",
                    "confidence",
                ]
            }
            for row in result["rows"]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.output} ({report['elapsed_seconds']} s)")


if __name__ == "__main__":
    main()
