import csv
import sys
from pathlib import Path

from app import app
from run_business_smoke_test_batch import FIELDNAMES, append_rows_to_google_sheet


def read_rows(path):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append({field: row.get(field, "") for field in FIELDNAMES})
        return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: python append_business_smoke_csv_to_google_sheet.py <csv> [<csv> ...]", file=sys.stderr)
        sys.exit(2)

    all_rows = []
    for value in sys.argv[1:]:
        path = Path(value)
        if not path.exists():
            print(f"Missing CSV: {path}", file=sys.stderr)
            sys.exit(2)
        rows = read_rows(path)
        all_rows.extend(rows)
        print(f"Loaded {len(rows)} rows from {path.name}")

    with app.app_context():
        if not append_rows_to_google_sheet(all_rows):
            print(
                "Google Sheets append skipped: set GOOGLE_SMOKE_TEST_SHEET_ID "
                "and GOOGLE_SERVICE_ACCOUNT_JSON.",
                file=sys.stderr,
            )
            sys.exit(2)

    print(f"Appended {len(all_rows)} rows to Google Sheets.")


if __name__ == "__main__":
    main()
