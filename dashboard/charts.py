"""Plotly theme, chart container and table formatting.

Charts sit on the card-stock panels. Figures are built in Python with the LIGHT values;
static/app.js swaps each light hex for its dark step at render time, so every color here
must come from the constants below (never ad-hoc hex) for dark mode to work.

Series colors are the colorblind-validated reference palette, used by meaning:
orange = the manager's bottom 10, blue = our adjusted list / the main series.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

# Categorical slots, fixed order (validated reference palette). Never cycle past 8.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE, ORANGE, AQUA = SERIES[0], SERIES[1], SERIES[2]

INK = "#1f1d19"         # primary text on card stock
INK_2 = "#555049"       # secondary text
MUTED = "#8a857c"       # axis ticks, de-emphasized marks (same in both modes)
GRID = "#e4e0d6"
AXIS = "#c9c3b6"
SURFACE = "#f8f6f0"     # card stock
BAND = "rgba(138,133,124,0.14)"   # neutral shaded spans (events, splits)

# Sequential blue for heatmaps and the floor map (light->dark = low->high).
SEQ_BLUE = [[0, "#cde2fb"], [0.25, "#9ec5f4"], [0.5, "#3987e5"], [0.75, "#1c5cab"], [1, "#0d366b"]]

FONT = 'Archivo, system-ui, -apple-system, "Segoe UI", sans-serif'


def figure(height: int = 320, legend: bool = True, hovermode: str | bool = "closest",
           **layout) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="none",
        height=height,
        autosize=True,
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=12, t=8 if not legend else 36, b=4),
        showlegend=legend,
        legend=dict(orientation="h", x=0, xanchor="left", y=1.02, yanchor="bottom",
                    title_text="", font=dict(color=INK_2), itemclick="toggle"),
        hovermode=hovermode,
        hoverlabel=dict(font=dict(family=FONT, size=12), align="left"),
        barcornerradius=4,
        bargap=0.4,
        bargroupgap=0.08,
        xaxis=dict(showgrid=False, zeroline=False, linecolor=AXIS, ticks="outside",
                   tickcolor=AXIS, ticklen=4, automargin=True, tickfont=dict(color=MUTED),
                   title_font=dict(color=INK_2)),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor="rgba(0,0,0,0)", automargin=True,
                   tickfont=dict(color=MUTED), title_font=dict(color=INK_2)),
    )
    fig.update_layout(**layout)
    return fig


def money_axis(fig: go.Figure, axis: str = "yaxis", title: str = "") -> None:
    fig.update_layout({axis: dict(tickprefix="$", tickformat="~s", title_text=title)})


def pct_axis(fig: go.Figure, axis: str = "yaxis", title: str = "") -> None:
    fig.update_layout({axis: dict(tickformat=".0%", title_text=title)})


def shade_spans(fig: go.Figure, spans: list[tuple], label_y: float = 1.0) -> None:
    """Neutral shaded x-spans with a small label at the top, e.g. events or data splits."""
    for start, end, label in spans:
        fig.add_vrect(x0=start, x1=end, fillcolor=BAND, line_width=0, layer="below")
        if label:
            fig.add_annotation(name="span-label", x=start, y=label_y, xref="x", yref="paper", text=label,
                               showarrow=False, xanchor="left", yanchor="top",
                               font=dict(size=10, color=INK_2))


# ---- table view ------------------------------------------------------------------------
def fmt_money(v, decimals: int = 0) -> str:
    if pd.isna(v):
        return "–"
    s = f"${abs(v):,.{decimals}f}"
    return f"−{s}" if v < 0 else s


def fmt_short_money(v) -> str:
    if pd.isna(v):
        return "–"
    a = abs(v)
    s = (f"${a / 1e6:,.2f}M" if a >= 1e6 else f"${a / 1e3:,.1f}K" if a >= 1e4 else f"${a:,.0f}")
    return f"−{s}" if v < 0 else s


def fmt_pct(v, decimals: int = 1) -> str:
    return "–" if pd.isna(v) else f"{v * 100:.{decimals}f}%"


def fmt_num(v, decimals: int = 0) -> str:
    return "–" if pd.isna(v) else f"{v:,.{decimals}f}"


def _default_fmt(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "–"
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d") if v == v.normalize() else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (bool,)) or type(v).__name__ == "bool_":
        return "Yes" if v else "No"
    return str(v)


def table(df: pd.DataFrame, formats: dict | None = None, links: dict | None = None,
          max_rows: int = 400, sortable: bool = True, numeric: set | None = None) -> Markup:
    """Render a DataFrame as an accessible, sortable HTML table.

    formats: column -> callable(value) -> str
    links:   column -> callable(row) -> href
    Raw values go into data-sort so sorting is numeric, not by formatted text.
    """
    formats, links = formats or {}, links or {}
    shown = df.head(max_rows)
    num_cols = numeric if numeric is not None else {
        c for c in shown.columns if pd.api.types.is_numeric_dtype(shown[c]) and shown[c].dtype != bool}
    out = [f'<div class="table-wrap"><table class="data-table{" sortable" if sortable else ""}"><thead><tr>']
    for c in shown.columns:
        cls = ' class="num"' if c in num_cols else ""
        out.append(f'<th scope="col"{cls}><button type="button">{html.escape(str(c))}</button></th>'
                   if sortable else f'<th scope="col"{cls}>{html.escape(str(c))}</th>')
    out.append("</tr></thead><tbody>")
    for _, row in shown.iterrows():
        out.append("<tr>")
        for c in shown.columns:
            v = row[c]
            text = formats[c](v) if c in formats else _default_fmt(v)
            text = html.escape(text)
            href = links[c](row) if c in links else ""
            if href:
                text = f'<a href="{html.escape(href)}">{text}</a>'
            sort = "" if pd.isna(v) else html.escape(str(v.isoformat() if hasattr(v, "isoformat") else v))
            cls = ' class="num"' if c in num_cols else ""
            out.append(f'<td{cls} data-sort="{sort}">{text}</td>')
        out.append("</tr>")
    out.append("</tbody></table></div>")
    if len(df) > max_rows:
        out.append(f'<p class="table-note">Showing first {max_rows:,} of {len(df):,} rows.</p>')
    return Markup("".join(out))


@dataclass
class Chart:
    id: str
    title: str
    fig: go.Figure
    source: str
    subtitle: str = ""
    table: Markup | None = None
    note: str = ""
    wide: bool = False
    third: bool = False     # three to a row (small multiples)
    extra: dict = field(default_factory=dict)

    @property
    def spec(self) -> Markup:
        # Escape "</" so the JSON can't close the surrounding <script> tag.
        return Markup(self.fig.to_json().replace("</", "<\\/"))
