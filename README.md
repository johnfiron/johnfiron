# johnfiron

## Collapse timeline chart

Interactive timeline showing:
- phase bands (Setup, Stress, Trigger, Cascade),
- current and historical cycle classification,
- highlighted collapse windows (including an **estimated 1927-1933** segment).

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

### Notes

- The Great Depression window is intentionally labeled **estimated** because high-frequency modern market stress inputs are not available for that period.
- Hover any point to see the date, phase, stress score, and core inputs.
