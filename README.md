# ERCOT Generator Offer Curve Forecast

Interactive 24-panel visualization of hourly offer curves with a forecast for **05/29/2026**.

## Setup

```bash
pip install -r requirements.txt
python offer_curve_analysis.py
```
Code testing was mainly done in .ipynb notebooks. [test file](newgrid.ipynb)  
The output is written to `offer_curves_forecast.html`. Open it in any browser.

## What it does

1. **Loads** `Generator_Offer_Curve_Data_for_Assessment.csv`
2. **Cleans** the data (see below)
3. **Forecasts** offer curves for 05/29/2026 (24 hours)
4. **Plots** a 6×4 grid — historical curves in light blue, forecast in orange

## Data Cleaning

| Issue | Action |
|---|---|
| Invalid timestamps | `pd.to_datetime(errors='coerce')`, drop NaT |
| Exact duplicate rows | `drop_duplicates()` |
| Duplicate timestamps | Keep first after sorting |
| Non-numeric MW/Price | `pd.to_numeric(errors='coerce')`, treat as NaN |
| Missing breakpoints | Drop pairs where either MW or Price is NaN |
| Price outliers | Drop points outside [−500, 5000] $/MWh (ERCOT market bounds) |
| Impossible MW values | Drop negative or > 2000 MW |
| Non-monotonic MW | Sort breakpoints by MW within each hour |
| HL/LL swap | Swap columns when Low Limit > High Limit |

## Forecast Method

Priority order per hour:
1. **Prior-year same date** (05/29/2025) — used for all 24 hours ✓
2. Median curve: same hour + month + weekday
3. Median curve: same hour + month
4. Median curve: same hour (full dataset)

## Assumptions

- ERCOT real-time price bounds: −$500 to $5000/MWh
- Unit capacity upper bound: 2000 MW (≈10× observed High Limit of ~200 MW)
- Duplicate timestamp: the first row (after sorting) is kept as the valid record
- Non-monotonic MW breakpoints are fixed by re-sorting (not dropping) unless a point was already removed by another rule

## AI Disclosure
Development was accelerated using Claude (Sonnet 4.6) to create the Plotly subplot layout.
