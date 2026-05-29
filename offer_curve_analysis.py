import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# CONFIG

INPUT_FILE   = r"offer_curve_data.csv"
OUTPUT_FILE  = r"offer_curves_forecast.html"
FORECAST_DATE = pd.Timestamp("2026-05-29")
N_BREAKPOINTS = 13

PRICE_MIN, PRICE_MAX = -500, 5000   # ERCOT real-time market bounds
MW_MAX               = 2000         # generous upper bound for this ~200 MW unit
PRICE_CLAMP          = PRICE_MAX    # cap, not drop, for visualisation clarity

# Column name helpers
MW_COLS    = [f"Quantity-MW{i}" for i in range(1, N_BREAKPOINTS + 1)]
PRICE_COLS = [f"Price{i}"       for i in range(1, N_BREAKPOINTS + 1)]



# STEP 1 – Load

print("Loading data …")
df_raw = pd.read_csv(INPUT_FILE)
print(f"Raw rows: {len(df_raw)}")



# STEP 2 – Exact duplicate rows

before = len(df_raw)
df_raw = df_raw.drop_duplicates()
print(f"  Removed {before - len(df_raw)} exact duplicate rows → {len(df_raw)} rows")



# STEP 3 – Parse / validate timestamps

df_raw["Timestamp"] = pd.to_datetime(df_raw["Timestamp"], errors="coerce")
bad_ts = df_raw["Timestamp"].isna().sum()
df_raw = df_raw.dropna(subset=["Timestamp"])
print(f"  Removed {bad_ts} rows with invalid timestamps → {len(df_raw)} rows")



# STEP 4 – Duplicate timestamps (keep first)

df_raw = df_raw.sort_values("Timestamp")
before = len(df_raw)
df_raw = df_raw.drop_duplicates(subset=["Timestamp"], keep="first")
print(f"  Removed {before - len(df_raw)} duplicate-timestamp rows → {len(df_raw)} rows")



# STEP 5 – Numeric coercion: MW, Price, HL, LL

for col in MW_COLS + PRICE_COLS + ["High Limit", "Low Limit"]:
    df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce")



# STEP 6 – High Limit / Low Limit integrity

swap_mask = (df_raw["Low Limit"] > df_raw["High Limit"]) & \
            df_raw["Low Limit"].notna() & df_raw["High Limit"].notna()
df_raw.loc[swap_mask, ["High Limit", "Low Limit"]] = \
    df_raw.loc[swap_mask, ["Low Limit", "High Limit"]].values
print(f"  Swapped {swap_mask.sum()} rows where Low Limit > High Limit")



# STEP 7 – Melt to long format (one row per breakpoint)

print("Reshaping to long format …")
meta_cols = ["Timestamp", "High Limit", "Low Limit", "Resource Status"]

records = []
for i in range(1, N_BREAKPOINTS + 1):
    tmp = df_raw[meta_cols + [f"Quantity-MW{i}", f"Price{i}"]].copy()
    tmp = tmp.rename(columns={f"Quantity-MW{i}": "MW", f"Price{i}": "Price"})
    tmp["bp"] = i
    records.append(tmp)

df_long = pd.concat(records, ignore_index=True)
print(f"  Long-format rows: {len(df_long)}")



# STEP 8 – Clean individual breakpoints

before = len(df_long)

# 8a. Drop where MW or Price is NaN
df_long = df_long.dropna(subset=["MW", "Price"])

# 8b. Price outliers
df_long = df_long[(df_long["Price"] >= PRICE_MIN) & (df_long["Price"] <= PRICE_MAX)]

# 8c. Impossible MW values (negative or absurdly large)
df_long = df_long[(df_long["MW"] >= 0) & (df_long["MW"] <= MW_MAX)]

print(f"  Removed {before - len(df_long)} invalid breakpoint rows "
      f"(NaN / price outlier / bad MW) → {len(df_long)} breakpoints")



# STEP 9 – Enforce monotonic MW per hour
#          (sort breakpoints by MW within each timestamp)

df_long = df_long.sort_values(["Timestamp", "MW"]).reset_index(drop=True)



# STEP 10 – Feature engineering

df_long["hour"]    = df_long["Timestamp"].dt.hour
df_long["date"]    = df_long["Timestamp"].dt.normalize()
df_long["month"]   = df_long["Timestamp"].dt.month
df_long["weekday"] = df_long["Timestamp"].dt.weekday   # 0=Mon … 6=Sun

print(f"Date range: {df_long['date'].min().date()} → {df_long['date'].max().date()}")
print(f"Unique dates: {df_long['date'].nunique()}")



# STEP 11 – Forecast curves for 05/29/2026

print("Building forecast curves …")

PRIOR_YEAR_DATE   = FORECAST_DATE - pd.DateOffset(years=1)   # 05/29/2025
FORECAST_MONTH    = FORECAST_DATE.month    # 5
FORECAST_WEEKDAY  = FORECAST_DATE.weekday()  # Friday = 4

def median_curve(subset: pd.DataFrame) -> pd.DataFrame:
    """Return median MW/Price curve from a long-format subset."""
    # Bin into N_BREAKPOINTS quantile positions and take medians
    if subset.empty:
        return pd.DataFrame(columns=["MW", "Price"])
    # Use rank-based binning within each curve then aggregate
    subset = subset.copy()
    subset["rank"] = subset.groupby("date")["MW"].rank(method="first").astype(int)
    med = subset.groupby("rank")[["MW", "Price"]].median().reset_index(drop=True)
    return med.sort_values("MW")

forecast_curves = {}   # hour → DataFrame(MW, Price)

for h in range(24):
    h_data = df_long[df_long["hour"] == h]

    # Priority 1: same date prior year
    py_data = h_data[h_data["date"] == PRIOR_YEAR_DATE]
    if not py_data.empty:
        fc = py_data[["MW", "Price"]].sort_values("MW").reset_index(drop=True)
        forecast_curves[h] = (fc, "Prior-year same date")
        continue

    # Priority 2: same hour + month + weekday
    sub2 = h_data[(h_data["month"] == FORECAST_MONTH) &
                  (h_data["weekday"] == FORECAST_WEEKDAY)]
    if len(sub2["date"].unique()) >= 3:
        forecast_curves[h] = (median_curve(sub2), "Median: same hour+month+weekday")
        continue

    # Priority 3: same hour + month
    sub3 = h_data[h_data["month"] == FORECAST_MONTH]
    if not sub3.empty:
        forecast_curves[h] = (median_curve(sub3), "Median: same hour+month")
        continue

    # Priority 4: full dataset median for this hour
    forecast_curves[h] = (median_curve(h_data), "Median: same hour (full year)")



# STEP 12 – Build 6×4 interactive Plotly figure

print("Building Plotly figure …")

ROWS, COLS = 6, 4
fig = make_subplots(
    rows=ROWS, cols=COLS,
    subplot_titles=[f"Hour {h:02d}" for h in range(24)],
    horizontal_spacing=0.06,
    vertical_spacing=0.08,
)

# Colour palette
HIST_COLOR    = "rgba(100, 180, 240, 0.18)"
HIST_LINE_CLR = "rgba(100, 180, 240, 0.35)"
FC_COLOR      = "#FF6B35"
FC_DOT_COLOR  = "#FF6B35"

for h in range(24):
    row = h // COLS + 1
    col = h % COLS  + 1
    show_legend = (h == 0)

    h_data = df_long[df_long["hour"] == h]
    dates  = h_data["date"].unique()

    # Historical curves (light blue)
    for i, d in enumerate(sorted(dates)):
        day_data = h_data[h_data["date"] == d].sort_values("MW")
        if len(day_data) < 2:
            continue
        fig.add_trace(
            go.Scatter(
                x=day_data["MW"],
                y=day_data["Price"],
                mode="lines",
                line=dict(color=HIST_LINE_CLR, width=0.8),
                fill=None,
                showlegend=(show_legend and i == 0),
                name="Historical",
                legendgroup="historical",
                hoverinfo="skip",
            ),
            row=row, col=col,
        )

    # Forecast curve (orange)
    fc_df, fc_method = forecast_curves[h]
    if not fc_df.empty:
        fig.add_trace(
            go.Scatter(
                x=fc_df["MW"],
                y=fc_df["Price"],
                mode="lines+markers",
                line=dict(color=FC_COLOR, width=2.2),
                marker=dict(color=FC_DOT_COLOR, size=5, symbol="circle"),
                showlegend=show_legend,
                name=f"Forecast {FORECAST_DATE.strftime('%m/%d/%Y')}",
                legendgroup="forecast",
                hovertemplate="MW: %{x:.1f}<br>Price: $%{y:.2f}/MWh<extra></extra>",
            ),
            row=row, col=col,
        )

# Layout
fig.update_layout(
    title=dict(
        text=(
            f"<b>ERCOT Generator Offer Curves — 24 Hours</b><br>"
            f"<sup>Historical (light blue) + Forecast {FORECAST_DATE.strftime('%m/%d/%Y')} (orange) | "
            f"Cleaned from {df_long['date'].nunique()} daily observations</sup>"
        ),
        font=dict(size=18, family="Georgia, serif"),
        x=0.5, xanchor="center",
    ),
    height=1400,
    width=1400,
    paper_bgcolor="#0f1923",
    plot_bgcolor="#0f1923",
    font=dict(color="#c8d8e8", family="Courier New, monospace", size=10),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(size=12),
        bgcolor="rgba(0,0,0,0.3)",
        bordercolor="#334455",
        borderwidth=1,
    ),
    margin=dict(l=50, r=30, t=140, b=50),
)

# Style all subplot axes
for h in range(24):
    row = h // COLS + 1
    col = h % COLS  + 1
    ax  = "" if (row == 1 and col == 1) else str(h + 1)
    fig.update_xaxes(
        title_text="MW" if row == ROWS else "",
        title_font=dict(size=8),
        tickfont=dict(size=7),
        gridcolor="#1e2d3d",
        linecolor="#334455",
        showgrid=True,
        row=row, col=col,
    )
    fig.update_yaxes(
        title_text="$/MWh" if col == 1 else "",
        title_font=dict(size=8),
        tickfont=dict(size=7),
        gridcolor="#1e2d3d",
        linecolor="#334455",
        showgrid=True,
        row=row, col=col,
    )

# Style subplot titles
for ann in fig.layout.annotations:
    ann.font = dict(size=10, color="#7fb3d3", family="Courier New, monospace")


# STEP 13 – Write HTML
fig.write_html(
    OUTPUT_FILE,
    include_plotlyjs="cdn",
    full_html=True,
    config={"scrollZoom": True, "displayModeBar": True},
)
print(f"\n✅  Output written to: {OUTPUT_FILE}")