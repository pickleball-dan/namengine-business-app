import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from app import app, build_original_payload, generate_shortlist_payload

try:
    import gspread
except ImportError:
    gspread = None


CASES = [
    {
        "test_id": "BUS001",
        "mode": "Business Curated",
        "brief": "Local service business, trustworthy and easy to refer",
        "form_data": {
            "pet_type": "Local service",
            "discovery_style": "Balanced mix",
            "style": "Classic",
            "timeless_vs_distinctive": "Mostly timeless",
            "familiarity_preference": "Recognizable but not overused",
            "pronunciation_importance": "Very important",
            "vibe": "Trustworthy",
            "cultural_context": "Suggestive",
            "partner_alignment": "Needs to feel credible, not cute.",
            "notes": "Home maintenance and repair business for busy families. Avoid handyman cliches and generic Solutions names.",
        },
    },
    {
        "test_id": "BUS002",
        "mode": "Business Curated",
        "brief": "SaaS app name, modern and searchable",
        "form_data": {
            "pet_type": "App / software",
            "discovery_style": "Unexpected finds",
            "style": "Modern",
            "timeless_vs_distinctive": "Mostly distinctive",
            "familiarity_preference": "Memorable and rarer",
            "pronunciation_importance": "Very important",
            "vibe": "Technical",
            "cultural_context": "Coined word",
            "partner_alignment": "Distinctive but not fake-startup nonsense.",
            "notes": "Workflow app for small teams. Should be short, searchable, and not sound like Slack, Notion, Asana, or Monday.",
        },
    },
    {
        "test_id": "BUS003",
        "mode": "Business Curated",
        "brief": "Premium creative studio",
        "form_data": {
            "pet_type": "Studio / agency",
            "discovery_style": "Balanced mix",
            "style": "Strong and tailored",
            "timeless_vs_distinctive": "Balanced",
            "familiarity_preference": "A little less common",
            "pronunciation_importance": "Helpful but not absolute",
            "vibe": "Premium",
            "cultural_context": "Premium / editorial",
            "partner_alignment": "Should feel polished but human.",
            "notes": "Brand and content studio for founders. Avoid corporate agency cliches.",
        },
    },
    {
        "test_id": "BUS004",
        "mode": "Business Curated",
        "brief": "Nonprofit name, warm and clear",
        "form_data": {
            "pet_type": "Nonprofit",
            "discovery_style": "Classic favorites",
            "style": "Soft and romantic",
            "timeless_vs_distinctive": "Mostly timeless",
            "familiarity_preference": "Very familiar and easy",
            "pronunciation_importance": "Very important",
            "vibe": "Human",
            "cultural_context": "Warm and human",
            "partner_alignment": "Mission should be clear without sounding generic.",
            "notes": "Community nonprofit focused on helping new parents access supplies and support.",
        },
    },
    {
        "test_id": "BUS005",
        "mode": "Business Curated",
        "brief": "Newsletter / media name with point of view",
        "form_data": {
            "pet_type": "Newsletter / media",
            "discovery_style": "Unexpected finds",
            "style": "Uncommon but usable",
            "timeless_vs_distinctive": "Mostly distinctive",
            "familiarity_preference": "A little less common",
            "pronunciation_importance": "Helpful but not absolute",
            "vibe": "Bold",
            "cultural_context": "Compound word",
            "partner_alignment": "Should feel smart, not bro-y.",
            "notes": "Newsletter about practical AI adoption for local businesses and operators.",
        },
    },
    {
        "test_id": "BUS006",
        "mode": "Business Original",
        "brief": "Original coined product name, clean and ownable",
        "original": True,
        "form_data": {
            "pet_type": "Product",
            "discovery_style": "Balanced mix",
            "style": "Modern",
            "vibe": "Creative",
            "familiarity_preference": "Memorable and rarer",
            "pronunciation_importance": "Very important",
            "cultural_context": "Coined word",
            "starting_letter": "V",
            "length_preference": "Balanced 2 syllables",
            "avoid_feel": "Too techy, hard to say, empty app name",
            "notes": "Consumer productivity product for saving decisions and preferences.",
        },
    },
    {
        "test_id": "BUS007",
        "mode": "Business Original",
        "brief": "Original studio name, editorial and warm",
        "original": True,
        "form_data": {
            "pet_type": "Studio / agency",
            "discovery_style": "Unexpected finds",
            "style": "Strong and tailored",
            "vibe": "Premium",
            "familiarity_preference": "A little less common",
            "pronunciation_importance": "Helpful but not absolute",
            "cultural_context": "Premium / editorial",
            "starting_letter": "",
            "length_preference": "Open to either",
            "avoid_feel": "Corporate, generic, too clever",
            "notes": "Naming and brand studio for early-stage founders.",
        },
    },
]

FIELDNAMES = [
    "Test ID",
    "Mode",
    "Brief / Parent Request",
    "Gender",
    "Discovery Style",
    "Cultural Feel",
    "Sibling / Family Context",
    "Generated Name",
    "Pronunciation",
    "Origin / Structure",
    "Meaning / Style",
    "Why / Fit Note",
    "Rank Shown",
    "Source",
    "User Reaction",
    "Usable? (Y/N)",
    "Quality Score (1-5)",
    "Novelty Score (1-5)",
    "Fit Score (1-5)",
    "Issue Type",
    "Notes",
    "Action Needed",
]


def get_smoke_worksheet():
    sheet_id = os.getenv("GOOGLE_SMOKE_TEST_SHEET_ID", "").strip()
    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    worksheet_name = os.getenv("GOOGLE_SMOKE_TEST_WORKSHEET", "Smoke Tests").strip() or "Smoke Tests"
    if not sheet_id or not credentials_json or gspread is None:
        return None

    credentials = json.loads(credentials_json)
    client = gspread.service_account_from_dict(credentials)
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(FIELDNAMES))
        worksheet.append_row(FIELDNAMES, value_input_option="USER_ENTERED")

    if not worksheet.row_values(1):
        worksheet.append_row(FIELDNAMES, value_input_option="USER_ENTERED")
    return worksheet


def append_rows_to_google_sheet(rows):
    worksheet = get_smoke_worksheet()
    if worksheet is None:
        return False
    values = [[row.get(field, "") for field in FIELDNAMES] for row in rows]
    if values:
        worksheet.append_rows(values, value_input_option="USER_ENTERED")
    return True


def row_for_item(case, item, rank, source):
    form = case["form_data"]
    return {
        "Test ID": case["test_id"],
        "Mode": case["mode"],
        "Brief / Parent Request": case["brief"],
        "Gender": form.get("pet_type", ""),
        "Discovery Style": form.get("discovery_style", ""),
        "Cultural Feel": form.get("cultural_context", ""),
        "Sibling / Family Context": form.get("partner_alignment", "") or form.get("notes", ""),
        "Generated Name": item.get("name", ""),
        "Pronunciation": item.get("pronunciation", ""),
        "Origin / Structure": item.get("origin") or item.get("structure", ""),
        "Meaning / Style": item.get("meaning") or item.get("style", ""),
        "Why / Fit Note": item.get("why") or item.get("fit_note", ""),
        "Rank Shown": rank,
        "Source": source,
        "User Reaction": "",
        "Usable? (Y/N)": "",
        "Quality Score (1-5)": "",
        "Novelty Score (1-5)": "",
        "Fit Score (1-5)": "",
        "Issue Type": "",
        "Notes": "",
        "Action Needed": "",
    }


def run_case(case):
    form = case["form_data"]
    if case["mode"] == "Business Original":
        payload = build_original_payload(form)
        return payload["names"], "openai_or_fallback_original"
    payload = generate_shortlist_payload(form)
    source = "fallback" if payload.get("used_fallback") else "openai"
    return payload["names"], source


def main():
    append_to_sheets = "--append-to-sheets" in sys.argv
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(__file__).with_name(f"namengine_business_smoke_test_{stamp}.csv")
    rows = []
    with app.test_request_context("/"):
        for case in CASES:
            print(f"Running {case['test_id']} {case['mode']}: {case['brief']}")
            names, source = run_case(case)
            for rank, item in enumerate(names, start=1):
                rows.append(row_for_item(case, item, rank, source))

    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(out_path)
    if append_to_sheets:
        if append_rows_to_google_sheet(rows):
            print(f"Appended {len(rows)} rows to Google Sheets.")
        else:
            print(
                "Skipped Google Sheets append: set GOOGLE_SMOKE_TEST_SHEET_ID "
                "and GOOGLE_SERVICE_ACCOUNT_JSON.",
                file=sys.stderr,
            )
            sys.exit(2)


if __name__ == "__main__":
    main()
