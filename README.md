# johnfiron

## Collapse timeline chart

Interactive timeline showing:
- phase bands (Setup, Stress, Trigger, Cascade),
- current and historical cycle classification,
- highlighted collapse windows (including an **estimated 1927-1933** segment).
- rolling volatility chart for both stress score and phase regime changes (12-month window).

### 1) Build the dataset

```bash
python3 tools/build_timeline_data.py
```

This writes `data/timeline_data.json` from live FRED series.

### 2) Open the chart

Serve the folder and open `index.html`:

```bash
python3 -m http.server 8000
```

Then visit:

`http://localhost:8000/index.html`

## Deploy to GitHub Pages

This repo includes `.github/workflows/deploy-pages.yml` to publish the dashboard.

### One-time repo setting

In GitHub:
1. Open **Settings -> Pages**
2. Under **Build and deployment**, set **Source** to **GitHub Actions**

### Publish flow

- On every push to `main`, GitHub Actions will:
  1. run `python3 tools/build_timeline_data.py`
  2. package `index.html` + `data/`
  3. deploy to GitHub Pages

### Site URL

For this repository name, the site URL format is:

`https://johnfiron.github.io/johnfiron/`

### Notes

- The Great Depression window is intentionally labeled **estimated** because high-frequency modern market stress inputs are not available for that period.
- Hover any point to see the date, phase, stress score, and core inputs.
- The dashboard now embeds a **data request status panel** showing every live source call, row counts, date coverage, and any fetch errors, so missing series are transparent and traceable.
