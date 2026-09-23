"""Import original partner archives into a separate, source-traceable local store."""

import argparse
import json
from pathlib import Path

from backend.partner_import import import_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iek", type=Path)
    parser.add_argument("--systeme", type=Path)
    parser.add_argument("--sources", type=Path, default=Path("data/partners/sources"))
    parser.add_argument("--reports", type=Path, default=Path("data/partners"))
    args = parser.parse_args()
    for company, path in [("iek", args.iek), ("systeme", args.systeme)]:
        if path:
            report = import_archive(path, company, args.sources)
            args.reports.mkdir(parents=True, exist_ok=True)
            out = args.reports / f"{company}-audit.json"
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(company, report["products"], "SKU;", report["events"], flush=True)


if __name__ == "__main__":
    main()
