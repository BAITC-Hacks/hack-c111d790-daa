"""python -m scripts.dataset demo|to-csv|from-csv. UTF-8 BOM, semicolon delimiters."""

import argparse
import csv
import json
from pathlib import Path

from backend.demo import make_demo
from backend.schemas import Dataset

TABLES = ("categories", "suppliers", "products", "sales", "inventory", "stockouts", "inbound", "materials")


def to_csv(data: Dataset, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    payload = data.model_dump(mode="json")
    manifest = {k: v for k, v in payload.items() if k not in TABLES}
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name in TABLES:
        rows = payload[name]
        if not rows:
            continue
        with (directory / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)


def from_csv(directory: Path) -> Dataset:
    payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    for name in TABLES:
        path = directory / f"{name}.csv"
        if not path.exists():
            payload[name] = []
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            payload[name] = list(csv.DictReader(handle, delimiter=";"))
    return Dataset.model_validate(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["demo", "to-csv", "from-csv"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action != "demo" and args.input is None:
        parser.error("--input is required for conversion")
    if args.action == "to-csv":
        to_csv(Dataset.model_validate_json(args.input.read_text(encoding="utf-8-sig")), args.output)
        return
    data = make_demo() if args.action == "demo" else from_csv(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    print(f"Validated {len(data.sales)} sales, {len(data.products)} products → {args.output}")


if __name__ == "__main__":
    main()
