# Case-00 Triborough — NYSCEF filing inventory

Canonical inventory: `nyscef_filing_inventory.json`

## Railway / executor configuration

Set these environment variables so LegalAI ingests the mounted Triborough corpus with verified NYSCEF page IDs:

```text
LEGALAI_MATTER_FOLDER=/app/data/case-00-triborough/source-pdfs/original:/Tribrough Full Docket
LEGALAI_NYSCEF_INVENTORY_PATH=data/case-00-triborough/nyscef_filing_inventory.json
```

Notes:

- `LEGALAI_MATTER_FOLDER` replaces the default `matter_docs` root for this executor only.
- `LEGALAI_NYSCEF_INVENTORY_PATH` must be set explicitly; unrelated matters do not load Triborough metadata.
- The misspelled `Tribrough` / `original:` volume segment is part of the mounted path and must be supplied via configuration, not hard-coded in application logic.
- `Archive.zip` remains excluded by allowed-extension filtering.
