from pdfminer.high_level import extract_text
from pathlib import Path
import csv

PDF_DIR = Path("static/pdfs")
INPUT_CSV = "output_clean.csv"
OUTPUT_CSV = "output_enriched.csv"

def get_text(pdf_path):
    try:
        return extract_text(pdf_path)
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return ""

def find_pdf(case_number):
    case_number = case_number.strip()
    if not case_number:
        return None

    for pdf in PDF_DIR.glob("*.pdf"):
        if pdf.name.startswith(case_number):
            return pdf

    return None

rows = []

with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)

    for row in reader:
        case_number = row.get("case_number", "").strip()

        pdf_file = find_pdf(case_number)

        if not pdf_file:
            continue

        print(f"Processing {case_number} -> {pdf_file.name}")

        text = get_text(pdf_file)

        if not text.strip():
            continue

        row["full_text"] = text[:20000]
        rows.append(row)

if not rows:
    print("❌ No rows processed")
    exit()

with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print(f"✅ Wrote {OUTPUT_CSV} with {len(rows)} rows")
