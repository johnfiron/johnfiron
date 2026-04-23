# johnfiron

## Collapse timeline chart

Interactive timeline showing:
- phase bands (Setup, Stress, Trigger, Cascade),
- current and historical cycle classification,
- highlighted collapse windows (including an **estimated 1927-1933** segment).
- rolling volatility chart for both stress score and phase regime changes (12-month window).
- cause/effect evidence explorer that auto-indexes papers and articles per data point with deterministic summaries.

### 1) Build the dataset

```bash
python3 tools/build_timeline_data.py
python3 tools/build_evidence_links.py
```

This writes:
- `data/timeline_data.json` from live FRED series
- `data/evidence_data.json` from dynamic OpenAlex + Crossref searches

### 2) Open the chart

Serve the folder and open `index.html`:

```bash
python3 -m http.server 8000
```

Then visit:

`http://localhost:8000/index.html`

Additional pages:
- `http://localhost:8000/sectors.html` (sector proxy dashboard)
- `http://localhost:8000/combined.html` (macro + sector combined view)

## Deploy to GitHub Pages

This repo includes `.github/workflows/deploy-pages.yml` to publish the dashboard.

### One-time repo setting

In GitHub:
1. Open **Settings -> Pages**
2. Under **Build and deployment**, set **Source** to **GitHub Actions**

### Publish flow

- On every push to `main`, GitHub Actions will:
  1. run `python3 tools/build_timeline_data.py`
  2. run `python3 tools/build_sector_data.py`
  3. run `python3 tools/build_evidence_supplemental.py`
  4. package `index.html` + `sectors.html` + `combined.html` + `data/`
  5. deploy to GitHub Pages

### Site URL

For this repository name, the site URL format is:

`https://johnfiron.github.io/johnfiron/`

### Notes

- The Great Depression window is intentionally labeled **estimated** because high-frequency modern market stress inputs are not available for that period.
- Hover any point to see the date, phase, stress score, and core inputs.
- The dashboard now embeds a **data request status panel** showing every live source call, row counts, date coverage, and any fetch errors, so missing series are transparent and traceable.
- The evidence explorer uses click-triggered **live** search for papers/articles from OpenAlex and Crossref, based on the clicked datapoint context (metric, value, phase, stress score, date).
- Supplemental Fed report factor references are prebuilt in `data/evidence_supplemental.json` via `tools/build_evidence_supplemental.py`.
- Phase is calculated (not manual) from weighted component scores with explicit phase transition rules; these rules are shown in the UI under **How phase is determined**.
- Evidence is now interaction-driven: click any line data point on the charts to open ranked articles/papers and related Fed supplemental factors for that point.
