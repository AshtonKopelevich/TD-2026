"""One builder per chapter. Each returns a context dict for templates/chapter.html.

Everything that states a result (headlines, "what this means", tiles) is computed from the
marts, so the real data drops in without edits. Column names follow docs/mart_contracts.md.
"""
from __future__ import annotations

import html
from dataclasses import replace
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from markupsafe import Markup

from .charts import (AQUA, AXIS, BAND, BLUE, GRID, INK, INK_2, MUTED, ORANGE, SEQ_BLUE, SERIES, SURFACE,
                     Chart, figure, fmt_money, fmt_num, fmt_pct, fmt_short_money, money_axis, pct_axis,
                     shade_spans, table)
from .contract import (BUDGET, CAUSE_ACTION, CLASSES, EVENT_TYPES, FLAGS_MACHINE, FLAGS_NOT_MACHINE,
                       MACHINE_SPOTS, MART_CHAPTER, MAX_ACTION_TYPES, ACTION_SHORT, SHIFTS, SPOT_NOTES,
                       SPOTS, shift_of)
from .data import T, Filters, _db_stamp, action_catalog, query, zone_name

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIER_ORDER = ["Base", "Bronze", "Silver", "Gold", "Platinum"]

# The story, in reading order. (endpoint, title, question tag, question)
CHAPTERS = [
    ("verdict", "The verdict", "Q1",
     "Which machines are truly underperforming once exposure, availability and luck are accounted for?"),
    ("machines", "Machine explorer", "Q1",
     "What explains any one machine's result: demand, luck, downtime or its spot?"),
    ("demand", "Floor demand", "Q2",
     "What changed in demand across the floor over the six months, and why?"),
    ("downtime", "Downtime", "Q3",
     "How much play was lost to downtime, and when?"),
    ("guests", "Players and comps", "Q4 and Q5",
     "What did tracked players wager, get back and net, and what did the comp program cost?"),
    ("forecast", "Forecast", "Model",
     "Can we forecast daily coin-in better than a flat average, and what does that change?"),
    ("plan", "The $100K plan", "Q6",
     "Which actions would we fund with $100,000, and how would we know they worked?"),
]
CHAPTER_NUM = {ep: i + 1 for i, (ep, *_rest) in enumerate(CHAPTERS)}


def tile(label, value, sub="", tone=""):
    return {"label": label, "value": value, "sub": sub, "tone": tone}


def cls_label(code) -> str:
    return CLASSES.get(code, (str(code).replace("_", " ").capitalize(),))[0] if pd.notna(code) else "Not classified"


def cls_spot(code) -> str:
    return CLASSES.get(code, (None, "Unclear"))[1] if pd.notna(code) else "Unclear"


def cls_cause(code) -> str:
    return CLASSES.get(code, (None, None, str(code)))[2]


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _ordered(values, order) -> list:
    present = [v for v in pd.unique(values) if pd.notna(v)]
    return [v for v in order if v in present] + sorted(v for v in present if v not in order)


def _hour_label(h: int) -> str:
    return f"{(h % 12) or 12} {'a.m.' if h % 24 < 12 else 'p.m.'}"


def _full_weeks(df: pd.DataFrame, col: str, f: Filters) -> pd.DataFrame:
    """Keep weeks wholly inside the period (partial edge weeks look like dips)."""
    full = (df[col] >= pd.Timestamp(f.start)) & (df[col] + pd.Timedelta(days=6) <= pd.Timestamp(f.end))
    return df[full] if full.any() else df


@lru_cache(maxsize=4)
def _positions(_stamp: float) -> pd.DataFrame:
    return query(f"""
        SELECT machine_id, arg_max(location_id, gaming_date) location_id,
               arg_max(zone_id, gaming_date) zone_id, arg_max(zone_name, gaming_date) zone_name,
               arg_max(bank_id, gaming_date) bank_id, arg_max(manufacturer, gaming_date) manufacturer,
               arg_max(theme, gaming_date) theme, arg_max(volatility_class, gaming_date) volatility_class
        FROM {T('mart_machine_daily')} GROUP BY machine_id""")


def positions() -> pd.DataFrame:
    """Each machine's latest position (machines move, so this is for labels only)."""
    return _positions(_db_stamp())


def scorecard(f: Filters) -> pd.DataFrame:
    sc = query(f"SELECT * FROM {T('mart_machine_scorecard')}").merge(positions(), on="machine_id", how="left")
    if f.zone:
        sc = sc[sc.zone_id == f.zone]
    if f.bank:
        sc = sc[sc.bank_id == f.bank]
    sc = sc.assign(label=sc.primary_classification.map(cls_label),
                   spot=sc.primary_classification.map(cls_spot),
                   on_adjusted=sc.adjusted_rank <= 10)
    return sc


def machine_link(f: Filters):
    return lambda mid: f"/machines/{mid}{f.qs()}"


def floor_kpis(f: Filters, location: bool = True) -> dict:
    w, p = f.where(location=location)
    return query(f"""
        SELECT SUM(coin_in_usd) coin_in, SUM(house_win_usd) house_win, SUM(theo_usd) theo,
               SUM(available_seconds) avail, SUM(scheduled_seconds) sched,
               SUM(carded_coin_in_usd) carded, COUNT(DISTINCT machine_id) machines, COUNT(*) machine_days
        FROM {T('mart_machine_daily')} WHERE {w}""", p).iloc[0].to_dict()


# =========================================================================================
# 1 · The verdict (Q1)
# =========================================================================================
def verdict_story(sc: pd.DataFrame) -> tuple[str, str, str]:
    """(headline, meaning, top classification code) for the manager's list."""
    naive = sc[sc.naive_bottom_10]
    n = len(naive)
    if n == 0:
        return ("None of the manager's 10 machines sit in this part of the floor.",
                "Clear the zone or bank filter to see the full list.", "")
    counts = naive.primary_classification.value_counts()
    top_code, top_n = counts.index[0], int(counts.iloc[0])
    weak = int((naive.primary_classification == "weak_demand_candidate").sum())
    whose = "the manager's 10" if n == 10 else f"the {n} of the manager's machines in this view"
    if weak == 0:
        head = f"None of {whose} is a weak machine worth replacing."
    elif weak == n:
        head = f"All of {whose} are weak machines worth replacing."
    else:
        head = f"Only {weak} of {whose} {'is a weak machine' if weak == 1 else 'are weak machines'} worth replacing."
    if top_code != "weak_demand_candidate":
        head += (f" All {n} earn little because of {cls_cause(top_code)}." if top_n == n
                 else f" {top_n} of them earn little because of {cls_cause(top_code)}.")
    if top_code == "weak_demand_candidate":
        meaning = f"Replacing them should help: {CAUSE_ACTION[top_code]}."
    else:
        meaning = (f"Replacing these machines would spend money without fixing the cause. "
                   f"The evidence says to {CAUSE_ACTION.get(top_code, 'look closer')}.")
    return head, meaning, top_code


def _flag_cell(v) -> str:
    if v is None or (not isinstance(v, (bool, np.bool_)) and pd.isna(v)):
        return '<td class="flag na"><span aria-label="Not tested">–</span></td>'
    return ('<td class="flag on"><span aria-label="Yes">●</span></td>' if v
            else '<td class="flag off"><span aria-label="No">○</span></td>')


def elimination_grid(naive: pd.DataFrame, f: Filters) -> Markup:
    """The manager's 10, with every evidence flag, so overlapping explanations stay visible."""
    link = machine_link(f)
    head = ['<div class="table-wrap"><table class="data-table grid-table"><thead>',
            '<tr><th rowspan="2" scope="col" class="num">Rank</th><th rowspan="2" scope="col">Machine</th>',
            '<th rowspan="2" scope="col">Zone</th><th rowspan="2" scope="col" class="num">House win</th>',
            '<th rowspan="2" scope="col" class="num">Adjusted rank</th>',
            f'<th colspan="{len(FLAGS_NOT_MACHINE)}" scope="colgroup" class="group">Not the machine\'s fault</th>',
            f'<th colspan="{len(FLAGS_MACHINE)}" scope="colgroup" class="group machine">The machine</th>',
            '<th rowspan="2" scope="col">Diagnosis</th><th rowspan="2" scope="col">Why</th></tr><tr>']
    for _, lab in FLAGS_NOT_MACHINE + FLAGS_MACHINE:
        head.append(f'<th scope="col" class="flag-head">{html.escape(lab)}</th>')
    head.append("</tr></thead><tbody>")
    rows = []
    for r in naive.sort_values("naive_rank").itertuples():
        cells = "".join(_flag_cell(getattr(r, col, None)) for col, _ in FLAGS_NOT_MACHINE + FLAGS_MACHINE)
        also = ' <span class="also" title="Also on our adjusted bottom 10">also adjusted #' \
               f'{int(r.adjusted_rank)}</span>' if r.on_adjusted else ""
        rows.append(
            f'<tr><td class="num">{int(r.naive_rank)}</td>'
            f'<td><a href="{link(r.machine_id)}">{html.escape(r.machine_id)}</a></td>'
            f'<td>{html.escape(str(r.zone_name))}</td><td class="num">{fmt_money(r.house_win_usd)}</td>'
            f'<td class="num{" hit" if r.on_adjusted else ""}">{int(r.adjusted_rank)}</td>{cells}'
            f'<td><span class="diag diag-{html.escape(r.spot.lower().replace(" ", "-"))}">{html.escape(r.label)}</span></td>'
            f'<td class="why">{html.escape(str(r.classification_reason))}</td></tr>')
    legend = ('<p class="grid-legend"><span>● yes</span><span>○ no</span><span>– not tested</span>'
              '<span>Bold adjusted ranks are in our bottom 10 too.</span>'
              '<span>Flags can overlap; the diagnosis is the strongest one.</span></p>')
    return Markup("".join(head + rows) + "</tbody></table></div>" + legend)


def verdict(f: Filters) -> dict:
    sc = scorecard(f)
    naive, adj = sc[sc.naive_bottom_10], sc[sc.on_adjusted]
    head, meaning, top_code = verdict_story(sc)
    overlap = len(set(naive.machine_id) & set(adj.machine_id))

    # Two rankings on one plot: what the manager ranked on vs the exposure-adjusted rate.
    group = pd.Series("Other machines", index=sc.index)
    group[sc.naive_bottom_10] = "Manager's bottom 10"
    group[sc.on_adjusted] = "Adjusted bottom 10"
    group[sc.naive_bottom_10 & sc.on_adjusted] = "On both lists"
    sc = sc.assign(group=group)
    fig = figure(height=380)
    for name, color, size in [("Other machines", MUTED, 7), ("Manager's bottom 10", ORANGE, 11),
                              ("Adjusted bottom 10", BLUE, 11), ("On both lists", AQUA, 12)]:
        d = sc[sc.group == name]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(
            x=d.house_win_usd, y=d.expected_contribution_per_available_hour, mode="markers", name=name,
            marker=dict(color=color, size=size, opacity=0.5 if name == "Other machines" else 1,
                        line=dict(color=SURFACE, width=2)),
            customdata=d[["machine_id", "label", "zone_name"]],
            hovertemplate="<b>%{customdata[0]}</b>, %{customdata[2]}<br>House win %{x:$,.0f}<br>"
                          "Expected contribution %{y:$,.2f} per open hour<br>%{customdata[1]}<extra></extra>"))
    money_axis(fig, "xaxis", "Total house win, Jan–Jun (how the manager ranked)")
    fig.update_layout(yaxis=dict(tickprefix="$", title_text="Expected contribution per open hour"))
    rankings = Chart("verdict-rankings", "Two ways to rank the same floor", fig, "mart_machine_scorecard",
                     subtitle="Left is low total house win. Low is low expected win per hour the machine "
                              "could be played, after its own costs. Luck is taken out of the second measure.",
                     table=table(sc[["machine_id", "zone_name", "group", "naive_rank", "adjusted_rank",
                                     "house_win_usd", "expected_contribution_per_available_hour", "label"]]
                                 .sort_values("naive_rank")
                                 .rename(columns={"machine_id": "Machine", "zone_name": "Zone", "group": "List",
                                                  "naive_rank": "Manager rank", "adjusted_rank": "Adjusted rank",
                                                  "house_win_usd": "House win",
                                                  "expected_contribution_per_available_hour": "Expected contribution / hr",
                                                  "label": "Diagnosis"}),
                                 {"House win": fmt_money, "Expected contribution / hr": lambda v: fmt_money(v, 2)}),
                     wide=True)

    listed = pd.concat([naive.assign(list="Manager's bottom 10"), adj.assign(list="Adjusted bottom 10")]) \
        .drop_duplicates("machine_id").sort_values("theo_per_available_hour", ascending=False)
    fig2 = figure(height=max(300, 60 + 22 * len(listed)))
    for r in listed.itertuples():
        fig2.add_shape(type="line", x0=r.peer_theo_per_hour, x1=r.theo_per_available_hour,
                       y0=r.machine_id, y1=r.machine_id, line=dict(color=AXIS, width=2), layer="below")
    fig2.add_trace(go.Scatter(x=listed.peer_theo_per_hour, y=listed.machine_id, mode="markers",
                              name="Zone neighbours", customdata=listed.zone_name,
                              marker=dict(color=MUTED, size=10, symbol="line-ns-open", line=dict(width=2, color=MUTED)),
                              hovertemplate="%{customdata} neighbours: %{x:$,.2f}/hr<extra></extra>"))
    for name, color in [("Manager's bottom 10", ORANGE), ("Adjusted bottom 10", BLUE)]:
        d = listed[listed.list == name]
        fig2.add_trace(go.Scatter(x=d.theo_per_available_hour, y=d.machine_id, mode="markers", name=name,
                                  marker=dict(color=color, size=10, line=dict(color=SURFACE, width=2)),
                                  customdata=d[["zone_name", "peer_rate_ratio"]],
                                  hovertemplate="<b>%{y}</b> in %{customdata[0]}: %{x:$,.2f}/hr<br>"
                                                "%{customdata[1]:.0%} of its neighbours<extra></extra>"))
    fig2.update_layout(xaxis=dict(tickprefix="$", title_text="Theo per open hour", showgrid=True, gridcolor=GRID),
                       yaxis=dict(showgrid=False, type="category", categoryorder="array",
                                  categoryarray=list(listed.machine_id)))
    vs_zone = Chart("verdict-zone", "Machine or spot?", fig2, "mart_machine_scorecard",
                    subtitle="Each listed machine against its zone neighbours on the same days. Close to the "
                             "tick means the spot is the limit; far below it points at the machine.",
                    table=table(listed[["machine_id", "list", "zone_name", "theo_per_available_hour",
                                        "peer_theo_per_hour", "peer_rate_ratio"]],
                                {"theo_per_available_hour": lambda v: fmt_money(v, 2),
                                 "peer_theo_per_hour": lambda v: fmt_money(v, 2), "peer_rate_ratio": fmt_pct}))

    gap = listed.assign(gap=listed.luck_residual_usd / listed.coin_in_usd)
    fig3 = figure(height=fig2.layout.height)
    fig3.add_vline(x=0, line_color=AXIS, line_width=1)
    for name, color in [("Manager's bottom 10", ORANGE), ("Adjusted bottom 10", BLUE)]:
        d = gap[gap.list == name]
        fig3.add_trace(go.Scatter(
            x=d.gap, y=d.machine_id, mode="markers", name=name,
            marker=dict(color=color, size=10, line=dict(color=SURFACE, width=2)),
            error_x=dict(type="data", symmetric=False, array=d.bootstrap_hold_gap_high - d.gap,
                         arrayminus=d.gap - d.bootstrap_hold_gap_low, color=color, thickness=2, width=4),
            customdata=d[["bootstrap_hold_gap_low", "bootstrap_hold_gap_high", "luck_q_value"]],
            hovertemplate="<b>%{y}</b>: hold %{x:+.2%} vs. expected<br>95%% luck interval "
                          "%{customdata[0]:+.2%} to %{customdata[1]:+.2%}<br>q = %{customdata[2]:.2f}<extra></extra>"))
    fig3.update_layout(xaxis=dict(tickformat="+.1%", title_text="Actual hold minus expected hold", showgrid=True,
                                  gridcolor=GRID),
                       yaxis=dict(showgrid=False, type="category", categoryorder="array",
                                  categoryarray=list(listed.machine_id)))
    luck = Chart("verdict-luck", "Is it just luck?", fig3, "mart_machine_scorecard",
                 subtitle="Bars are the block-bootstrap luck interval. One that crosses zero means luck "
                          "can't be ruled out; it doesn't prove the machine is fine.",
                 table=table(gap[["machine_id", "list", "gap", "bootstrap_hold_gap_low", "bootstrap_hold_gap_high",
                                  "luck_z_score", "luck_q_value"]],
                             {"gap": lambda v: fmt_pct(v, 2), "bootstrap_hold_gap_low": lambda v: fmt_pct(v, 2),
                              "bootstrap_hold_gap_high": lambda v: fmt_pct(v, 2),
                              "luck_z_score": lambda v: fmt_num(v, 2), "luck_q_value": lambda v: fmt_num(v, 3)}))

    counts = sc.label.value_counts().sort_values()
    fig4 = figure(height=260, legend=False)
    fig4.add_trace(go.Bar(x=counts.values, y=counts.index, orientation="h", marker_color=BLUE,
                          text=counts.values, textposition="outside", cliponaxis=False,
                          textfont=dict(color=INK_2), hovertemplate="%{y}: %{x} machines<extra></extra>"))
    fig4.update_layout(xaxis=dict(showgrid=True, gridcolor=GRID, title_text="Machines"), yaxis=dict(showgrid=False))
    mix = Chart("verdict-mix", "Every machine's diagnosis", fig4, "mart_machine_scorecard",
                subtitle="The whole floor, so the manager's 10 can be read against it.",
                table=table(counts.rename("Machines").rename_axis("Diagnosis").reset_index().iloc[::-1]), wide=True)

    adj_t = adj.sort_values("adjusted_rank")[["adjusted_rank", "machine_id", "zone_name",
                                              "expected_contribution_per_available_hour", "peer_rate_ratio",
                                              "availability_ratio", "naive_bottom_10", "label",
                                              "classification_reason"]]
    adj_t.columns = ["Rank", "Machine", "Zone", "Expected contribution / hr", "Vs. neighbours", "Availability",
                     "On manager's list", "Diagnosis", "Why"]
    return {
        "headline": head,
        "lede": "The manager ranked machines by total house win. We re-ranked them by expected win per hour "
                "they could actually be played, after their own costs, then tested each one for luck, "
                "location, downtime, repairs and a hold gap.",
        "rail": [
            tile("Also on our adjusted list", f"{overlap} of {len(naive)}", "Same machines, different reasons"),
            tile("Weak machines to replace", str(int((naive.primary_classification == "weak_demand_candidate").sum())),
                 "In the manager's 10"),
            tile("Luck can't be ruled out", str(int(naive.luck_compatible.fillna(False).sum())),
                 "Interval crosses zero"),
            tile("Their rate vs. neighbours", fmt_pct(naive.peer_rate_ratio.median(), 0), "Median of the 10"),
            tile("Their availability", fmt_pct(naive.available_seconds.sum() / naive.scheduled_seconds.sum()
                                               if len(naive) else None), "Open hours ÷ scheduled hours"),
        ],
        "sections": [
            {"title": "Which of the manager's 10 survive each test",
             "intro": "Each column is one way a machine can look weak without being weak. A machine is a "
                      "replacement candidate only if its weakness survives them.",
             "blocks": [elimination_grid(naive, f)], "source": "mart_machine_scorecard"},
            {"charts": [rankings, vs_zone, luck, mix]},
            {"title": "Our adjusted bottom 10",
             "intro": "Ranked on expected contribution per open hour. A low rank alone doesn't prove a "
                      "replacement would pay; the diagnosis says why.",
             "blocks": [table(adj_t, {"Expected contribution / hr": lambda v: fmt_money(v, 2),
                                      "Vs. neighbours": fmt_pct, "Availability": fmt_pct},
                              {"Machine": lambda r: machine_link(f)(r.Machine)})],
             "source": "mart_machine_scorecard"},
        ],
        "meaning": meaning,
        "scope_note": "Tests, ranks and diagnoses cover January to June 2025 as a whole. The period "
                      "filter doesn't change them; zone and bank filters narrow the lists.",
        "period_fixed": True,
    }


# =========================================================================================
# 2 · Machine explorer (Q1)
# =========================================================================================
def machine_period(f: Filters) -> pd.DataFrame:
    w, p = f.where()
    m = query(f"""
        SELECT machine_id, arg_max(zone_id, gaming_date) zone_id, arg_max(zone_name, gaming_date) zone_name,
               arg_max(bank_id, gaming_date) bank_id, arg_max(manufacturer, gaming_date) manufacturer,
               arg_max(theme, gaming_date) theme, arg_max(volatility_class, gaming_date) volatility_class,
               COUNT(*) AS days, SUM(coin_in_usd) coin_in, SUM(house_win_usd) house_win, SUM(theo_usd) theo,
               SUM(luck_residual_usd) luck,
               SUM(available_seconds) / NULLIF(SUM(scheduled_seconds), 0) availability,
               SUM(theo_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) theo_per_hr,
               SUM(house_win_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) win_per_hr,
               SUM(expected_contribution_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) net_per_hr
        FROM {T('mart_machine_daily')} WHERE {w} GROUP BY machine_id""", p)
    sc = query(f"SELECT machine_id, primary_classification, naive_bottom_10, adjusted_rank "
               f"FROM {T('mart_machine_scorecard')}")
    m = m.merge(sc, on="machine_id", how="left")
    return m.assign(label=m.primary_classification.map(cls_label),
                    naive_bottom_10=m.naive_bottom_10.fillna(False).astype(bool),
                    on_adjusted=(m.adjusted_rank <= 10).fillna(False).astype(bool))


def machines_story(f: Filters, m: pd.DataFrame | None = None) -> str:
    m = machine_period(f) if m is None else m
    if m.empty:
        return "No machines were on the floor in this selection."
    lo, hi = m.theo_per_hr.quantile(0.1), m.theo_per_hr.quantile(0.9)
    w, p = f.where()
    z = query(f"""SELECT zone_name, SUM(theo_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) r
                  FROM {T('mart_machine_daily')} WHERE {w} GROUP BY zone_name ORDER BY r DESC""", p)
    s = (f"Expected win per open hour runs from {fmt_money(lo, 2)} for the weakest tenth of machines "
         f"to {fmt_money(hi, 2)} for the strongest.")
    if len(z) > 1:
        s += f" {z.zone_name.iloc[0]} leads; {z.zone_name.iloc[-1]} trails at {z.r.iloc[-1] / z.r.iloc[0]:.0%} of its rate."
    return s


def machines(f: Filters) -> dict:
    m = machine_period(f)
    k = floor_kpis(f)
    fig = figure(height=420)
    top = float(np.nanmax([m.theo_per_hr.max(), m.win_per_hr.max(), 1])) * 1.05
    fig.add_trace(go.Scatter(x=[0, top], y=[0, top], mode="lines", name="Won exactly what theo expected",
                             line=dict(color=AXIS, width=1), hoverinfo="skip"))
    if f.diag:
        groups = [("Other machines", MUTED, m.primary_classification != f.diag),
                  (cls_label(f.diag), BLUE, m.primary_classification == f.diag)]
    else:
        groups = [("Other machines", MUTED, ~(m.naive_bottom_10 | m.on_adjusted)),
                  ("Manager's bottom 10", ORANGE, m.naive_bottom_10 & ~m.on_adjusted),
                  ("Adjusted bottom 10", BLUE, m.on_adjusted & ~m.naive_bottom_10),
                  ("On both lists", AQUA, m.naive_bottom_10 & m.on_adjusted)]
    for name, color, mask in groups:
        d = m[mask]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(
            x=d.theo_per_hr, y=d.win_per_hr, mode="markers", name=name,
            marker=dict(color=color, size=7 if color == MUTED else 11, opacity=0.5 if color == MUTED else 1,
                        line=dict(color=SURFACE, width=2)),
            customdata=d[["machine_id", "label", "zone_name", "availability"]],
            hovertemplate="<b>%{customdata[0]}</b>, %{customdata[2]}<br>Theo %{x:$,.2f}/hr, "
                          "actual %{y:$,.2f}/hr<br>Open %{customdata[3]:.0%} of scheduled hours<br>"
                          "%{customdata[1]}<extra></extra>"))
    fig.update_layout(xaxis=dict(tickprefix="$", title_text="Theo per open hour (what it should win)", rangemode="tozero"),
                      yaxis=dict(tickprefix="$", title_text="House win per open hour (what it won)"))
    scatter = Chart("machines-scatter", "Expected against actual, per open hour", fig,
                    "mart_machine_daily, mart_machine_scorecard",
                    subtitle="Above the line the machine ran lucky; below it, unlucky. Far left means few "
                             "players chose it, whatever the luck.", wide=True)

    by = "bank_id" if f.zone else "zone_name"
    w, p = f.where()
    g = query(f"""SELECT {by} grp, SUM(theo_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) theo_per_hr,
                         COUNT(DISTINCT machine_id) machines
                  FROM {T('mart_machine_daily')} WHERE {w} GROUP BY 1 ORDER BY 2""", p)
    fig2 = figure(height=320, legend=False)
    hi = g.grp == (f.bank if f.bank else None)
    fig2.add_trace(go.Bar(y=g.grp, x=g.theo_per_hr, orientation="h",
                          marker_color=[BLUE if (not f.bank or h) else MUTED for h in hi], customdata=g.machines,
                          hovertemplate="%{y}: %{x:$,.2f} theo per open hour, %{customdata} machines<extra></extra>"))
    fig2.update_layout(xaxis=dict(tickprefix="$", title_text="Theo per open hour", showgrid=True, gridcolor=GRID),
                       yaxis=dict(type="category", showgrid=False))
    where = Chart("machines-where", f"Expected win per open hour, by {'bank' if f.zone else 'zone'}", fig2,
                  "mart_machine_daily", subtitle="Ratio of sums over the period, so busy days weigh more.",
                  table=table(g.rename(columns={"grp": "Bank" if f.zone else "Zone",
                                                "theo_per_hr": "Theo per open hour", "machines": "Machines"}),
                              {"Theo per open hour": lambda v: fmt_money(v, 2)}))

    mix = m.label.value_counts().sort_values()
    fig3 = figure(height=320, legend=False)
    fig3.add_trace(go.Bar(y=mix.index, x=mix.values, orientation="h",
                          marker_color=[BLUE if (not f.diag or lab == cls_label(f.diag)) else MUTED for lab in mix.index],
                          hovertemplate="%{y}: %{x} machines<extra></extra>"))
    fig3.update_layout(xaxis=dict(showgrid=True, gridcolor=GRID, title_text="Machines"), yaxis=dict(showgrid=False))
    diag = Chart("machines-diag", "Diagnoses in this view", fig3, "mart_machine_scorecard",
                 subtitle="Pick one in the Diagnosis filter to light it up on the chart above.")

    t = m.sort_values("net_per_hr")[["machine_id", "zone_name", "bank_id", "manufacturer", "theme", "days",
                                     "coin_in", "house_win", "theo", "luck", "availability", "theo_per_hr",
                                     "net_per_hr", "label"]]
    t.columns = ["Machine", "Zone", "Bank", "Maker", "Game", "Days", "Coin-in", "House win", "Theo", "Luck",
                 "Availability", "Theo / hr", "Contribution / hr", "Diagnosis"]
    return {
        "headline": machines_story(f, m),
        "lede": "Everything here is recomputed for the period and place you pick, as ratios of sums. "
                "Sort the table, or open any machine for its day-by-day history.",
        "rail": [
            tile("Machines", fmt_num(k["machines"]), f.location_label),
            tile("Coin-in", fmt_short_money(k["coin_in"]), "Total wagered"),
            tile("Theo", fmt_short_money(k["theo"]), "Expected house win"),
            tile("Luck", fmt_short_money((k["house_win"] or 0) - (k["theo"] or 0)), "House win minus theo",
                 "pos" if (k["house_win"] or 0) >= (k["theo"] or 0) else "neg"),
            tile("Availability", fmt_pct(k["avail"] / k["sched"] if k["sched"] else None), "Open ÷ scheduled hours"),
        ],
        "sections": [
            {"charts": [scatter, where, diag]},
            {"title": "Every machine", "intro": f"{f.location_label}, {f.period_label}. Sorted weakest first "
                                                "by expected contribution per open hour.",
             "blocks": [table(t, {**{c: fmt_money for c in ["Coin-in", "House win", "Theo", "Luck"]},
                                  "Availability": fmt_pct, "Theo / hr": lambda v: fmt_money(v, 2),
                                  "Contribution / hr": lambda v: fmt_money(v, 2)},
                              {"Machine": lambda r: machine_link(f)(r.Machine)})],
             "source": "mart_machine_daily; Diagnosis from mart_machine_scorecard"},
        ],
        "meaning": "A machine far left on the scatter in a busy zone is the replacement case. A machine "
                   "near the line in a quiet zone needs a better spot, not a new cabinet.",
        "diag_filter": True,
        "scope_note": "Diagnoses come from the full January to June scorecard; every other number follows the filters.",
    }


def machine_detail(f: Filters, machine_id: str) -> dict | None:
    sc = query(f"SELECT * FROM {T('mart_machine_scorecard')} WHERE machine_id = ?", [machine_id])
    if sc.empty:
        return None
    s = sc.iloc[0]
    pos = positions().set_index("machine_id").loc[machine_id]
    w, p = f.where(location=False)
    d = query(f"SELECT * FROM {T('mart_machine_daily')} WHERE machine_id = ? AND {w} ORDER BY gaming_date",
              [machine_id, *p])

    fig = figure(height=320, hovermode="x unified")
    fig.add_trace(go.Scatter(x=d.gaming_date, y=d.theo_usd.cumsum(), name="Expected (theo)",
                             line=dict(color=MUTED, width=2), hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=d.gaming_date, y=d.house_win_usd.cumsum(), name="Actual house win",
                             line=dict(color=BLUE, width=2), hovertemplate="%{y:$,.0f}"))
    money_axis(fig, title="Running total")
    cum = Chart("machine-cum", "Actual against expected house win", fig, "mart_machine_daily",
                subtitle="The gap between the lines is luck. Luck wanders around the expected line; "
                         "a payout problem drifts steadily away from it.", wide=True)

    fig2 = figure(height=260, legend=False)
    fig2.add_trace(go.Bar(x=d.gaming_date, y=d.available_seconds / d.scheduled_seconds, marker_color=BLUE,
                          hovertemplate="%{x|%b %d}: open %{y:.0%} of scheduled hours<extra></extra>"))
    pct_axis(fig2, title="Open share of scheduled hours")
    fig2.update_layout(bargap=0.15, barcornerradius=1, yaxis_range=[0, 1.02])
    avail = Chart("machine-avail", "Daily availability", fig2, "mart_machine_daily")

    mm = query(f"SELECT * FROM {T('mart_machine_month')} WHERE machine_id = ? ORDER BY month_start", [machine_id])
    fig3 = figure(height=260, legend=False)
    fig3.add_hrect(y0=-1.96, y1=1.96, fillcolor=BAND, line_width=0, layer="below")
    fig3.add_trace(go.Bar(x=mm.month_start, y=mm.luck_z_score, marker_color=BLUE,
                          customdata=mm[["luck_residual_usd", "luck_q_value"]],
                          hovertemplate="%{x|%B}: z = %{y:.2f}<br>Luck %{customdata[0]:$,.0f}, "
                                        "q = %{customdata[1]:.2f}<extra></extra>"))
    fig3.update_layout(yaxis_title_text="Luck z-score", xaxis=dict(tickformat="%b", dtick="M1"))
    monthly = Chart("machine-month", "Luck by month", fig3, "mart_machine_month",
                    subtitle="The shaded band is ordinary luck (|z| under 1.96).",
                    table=table(mm[["month_start", "active_days", "coin_in_usd", "house_win_usd", "theo_usd",
                                    "luck_residual_usd", "luck_z_score", "luck_q_value"]],
                                {"month_start": lambda v: f"{v:%B}", "coin_in_usd": fmt_money,
                                 "house_win_usd": fmt_money, "theo_usd": fmt_money, "luck_residual_usd": fmt_money,
                                 "luck_z_score": lambda v: fmt_num(v, 2), "luck_q_value": lambda v: fmt_num(v, 3)}))

    runs = d.assign(run=(d.location_id != d.location_id.shift()).cumsum()).groupby("run").agg(
        Slot=("location_id", "first"), Zone=("zone_name", "first"), Bank=("bank_id", "first"),
        Game=("theme", "first"), From=("gaming_date", "min"), To=("gaming_date", "max"),
        Days=("gaming_date", "count"))
    tk = query(f"SELECT * FROM {T('mart_tickets')} WHERE machine_id = ? AND gaming_date BETWEEN ? AND ? "
               f"ORDER BY opened_at_utc", [machine_id, f.start, f.end])
    tk_t = pd.DataFrame({"Ticket": tk.operation_id, "Type": tk.event_type.map(lambda e: EVENT_TYPES.get(e, e)),
                         "Gaming date": tk.gaming_date, "Response (h)": tk.response_hours,
                         "Repair (h)": tk.repair_hours, "Theo/hr before": tk.before_theo_per_hour,
                         "Theo/hr after": tk.after_theo_per_hour})
    flags = [lab for col, lab in FLAGS_NOT_MACHINE + FLAGS_MACHINE if pd.notna(s.get(col)) and bool(s.get(col))]
    return {
        "headline": f"{cls_label(s.primary_classification)}. {s.classification_reason}",
        "lede": (f"{pos.zone_name}, bank {pos.bank_id}. {pos.manufacturer} cabinet running {pos.theme} "
                 f"({pos.volatility_class} volatility). Manager's rank {int(s.naive_rank)}, adjusted rank "
                 f"{int(s.adjusted_rank)}." + (f" Evidence flags: {', '.join(flags)}." if flags else "")),
        "rail": [
            tile("House win", fmt_short_money(s.house_win_usd), "January to June"),
            tile("Theo", fmt_short_money(s.theo_usd), "Expected house win"),
            tile("Luck", fmt_short_money(s.luck_residual_usd), f"z = {fmt_num(s.luck_z_score, 2)}, "
                 f"q = {fmt_num(s.luck_q_value, 2)}", "pos" if s.luck_residual_usd >= 0 else "neg"),
            tile("Hold", fmt_pct(s.observed_hold, 2), f"Expected {fmt_pct(s.expected_hold, 2)}"),
            tile("Availability", fmt_pct(s.availability_ratio)),
            tile("Theo per open hour", fmt_money(s.theo_per_available_hour, 2),
                 f"Neighbours {fmt_money(s.peer_theo_per_hour, 2)}"),
        ],
        "sections": [
            {"charts": [cum, avail, monthly]},
            {"title": "Where it stood", "blocks": [table(runs, {"From": lambda v: f"{v:%b %d}", "To": lambda v: f"{v:%b %d}"},
                                                          sortable=False)],
             "source": "mart_machine_daily (location_id by day)"},
            {"title": "Service tickets", "source": "mart_tickets",
             "blocks": [table(tk_t, {"Response (h)": lambda v: fmt_num(v, 1), "Repair (h)": lambda v: fmt_num(v, 1),
                                     "Theo/hr before": lambda v: fmt_money(v, 2), "Theo/hr after": lambda v: fmt_money(v, 2)})
                        if not tk.empty else Markup('<p class="empty">No tickets in this period.</p>')]},
        ],
        "title_override": f"Machine {machine_id}",
        "back": True,
    }


# =========================================================================================
# 3 · Floor demand (Q2)
# =========================================================================================
def _daily_demand(f: Filters) -> pd.DataFrame:
    w, p = f.where(alias="d")
    return query(f"""
        SELECT d.gaming_date, SUM(d.coin_in_usd) coin_in, COUNT(*) machine_days,
               any_value(fl.events_active) events_active, any_value(fl.federal_holiday) holiday,
               any_value(fl.weekday_index) weekday_index
        FROM {T('mart_machine_daily')} d LEFT JOIN {T('mart_floor_daily')} fl USING (gaming_date)
        WHERE {w} GROUP BY d.gaming_date ORDER BY d.gaming_date""", p)


def demand_story(f: Filters) -> str:
    daily = _daily_demand(f)
    if daily.empty:
        return "No play was recorded in this selection."
    daily["month"] = pd.to_datetime(daily.gaming_date).dt.to_period("M")
    mon = daily.groupby("month").agg(c=("coin_in", "sum"), md=("machine_days", "sum"))
    mon["r"] = mon.c / mon.md
    if len(mon) < 2:
        wd = daily.assign(r=daily.coin_in / daily.machine_days).groupby("weekday_index").r.mean()
        return (f"Coin-in averaged {fmt_money(mon.r.iloc[0])} per machine-day in {f.period_label}; "
                f"{WEEKDAYS[int(wd.idxmax())]}s were busiest.")
    change = mon.r.iloc[-1] / mon.r.iloc[0] - 1
    first, last = mon.index[0].start_time.date(), mon.index[-1].start_time.date()
    b = query(f"SELECT * FROM {T('mart_benchmark_month')} WHERE month_start IN (?, ?) ORDER BY month_start",
              [first, last])
    s = (f"Coin-in per machine-day {'rose' if change >= 0 else 'fell'} {abs(change):.1%} from "
         f"{first:%B} to {last:%B}.")
    if len(b) == 2:
        mo = b.missouri_coin_in_index.iloc[1] / b.missouri_coin_in_index.iloc[0] - 1
        lv = b.las_vegas_visitors_index.iloc[1] / b.las_vegas_visitors_index.iloc[0] - 1
        market = (np.sign(mo) == np.sign(change) or abs(mo) < 0.01) and abs(change - mo) < 0.03
        s += (f" Missouri slots moved {mo:+.1%} and Las Vegas visitors {lv:+.1%}, so the shift looks "
              f"{'market-wide, not specific to this floor' if market else 'specific to this floor'}.")
    return s


def demand(f: Filters) -> dict:
    daily = _daily_demand(f)
    daily["per_md"] = daily.coin_in / daily.machine_days
    daily["avg7"] = daily.coin_in.rolling(7, min_periods=1).sum() / daily.machine_days.rolling(7, min_periods=1).sum()
    daily["month"] = pd.to_datetime(daily.gaming_date).dt.to_period("M")
    mon = daily.groupby("month").agg(c=("coin_in", "sum"), md=("machine_days", "sum"))
    daily["month_mean"] = daily.month.map(mon.c / mon.md)
    daily["weekday"] = daily.weekday_index.map(lambda i: WEEKDAYS[int(i)] if pd.notna(i) else "")

    fig = figure(height=360, hovermode="x unified")
    fig.add_trace(go.Scatter(x=daily.gaming_date, y=daily.per_md, name="Daily", mode="lines",
                             line=dict(color=MUTED, width=1),
                             customdata=daily[["weekday", "events_active"]].fillna(""),
                             hovertemplate="%{y:$,.0f} (%{customdata[0]}) %{customdata[1]}"))
    fig.add_trace(go.Scatter(x=daily.gaming_date, y=daily.avg7, name="7-day average", mode="lines",
                             line=dict(color=BLUE, width=2), hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=daily.gaming_date, y=daily.month_mean, name="Monthly average", mode="lines",
                             line=dict(color=ORANGE, width=2, shape="hv"), hovertemplate="%{y:$,.0f}"))
    ev = daily.dropna(subset=["events_active"])
    if not ev.empty:
        spans = ev.assign(blk=(ev.events_active != ev.events_active.shift()).cumsum()) \
            .groupby("blk").agg(start=("gaming_date", "min"), end=("gaming_date", "max"), name=("events_active", "first"))
        shade_spans(fig, [(pd.Timestamp(r.start) - pd.Timedelta(hours=12), pd.Timestamp(r.end) + pd.Timedelta(hours=12),
                           r.name) for r in spans.itertuples()])
    money_axis(fig, title="Coin-in per machine-day")
    trend = Chart("demand-trend", "Daily demand " + ("on the whole floor" if not f.zone else f"in {f.location_label}"),
                  fig, "mart_machine_daily, events from mart_floor_daily",
                  subtitle="Coin-in per machine on the floor, so days with fewer machines compare fairly. "
                           "Shaded spans are events.",
                  table=table(daily[["gaming_date", "weekday", "coin_in", "machine_days", "per_md", "events_active",
                                     "holiday"]],
                              {"coin_in": fmt_money, "per_md": fmt_money}), wide=True)

    months = [p.start_time for p in mon.index]
    b = query(f"SELECT * FROM {T('mart_benchmark_month')} ORDER BY month_start")
    b = b[pd.to_datetime(b.month_start).isin(months)] if months else b
    fig2 = figure(height=320, hovermode="x unified")
    for i, (col, name) in enumerate([("property_coin_in_index", "This casino (per machine-day)"),
                                     ("missouri_coin_in_index", "Missouri slot coin-in"),
                                     ("las_vegas_visitors_index", "Las Vegas visitors")]):
        y = b[col] / b[col].iloc[0] * 100 if len(b) else b[col]
        fig2.add_trace(go.Scatter(x=b.month_start, y=y, name=name, mode="lines+markers",
                                  line=dict(color=SERIES[i], width=2), marker=dict(size=8),
                                  hovertemplate="%{y:.1f}"))
    fig2.add_hline(y=100, line_color=AXIS, line_width=1)
    fig2.update_layout(yaxis_title_text="Index, first month = 100", xaxis=dict(tickformat="%b", dtick="M1"))
    bench = Chart("demand-bench", "This floor, or the whole market?", fig2, "mart_benchmark_month",
                  subtitle="Indexed so different units share one axis. Missouri and Las Vegas figures are "
                           "real public data and describe those markets, not this casino's guests.",
                  table=table(b[["month_start", "property_coin_in_per_machine_day", "missouri_coin_in_usd",
                                 "las_vegas_visitor_volume", "missouri_status", "visitation_status"]],
                              {"month_start": lambda v: f"{v:%B}", "property_coin_in_per_machine_day": fmt_money,
                               "missouri_coin_in_usd": fmt_short_money, "las_vegas_visitor_volume": fmt_num}),
                  note="Not affected by zone or bank.")

    wm, pm = f.where_month()
    v = query(f"""SELECT month_start, SUM(observed_visits) visits, SUM(visit_assigned_coin_in_usd) coin_in
                  FROM {T('mart_visits_month')} WHERE {wm} GROUP BY 1 ORDER BY 1""", pm)
    v["per_visit"] = v.coin_in / v.visits
    fig3 = figure(height=320, hovermode="x unified")
    for i, (col, name) in enumerate([("visits", "Recorded visits"), ("per_visit", "Wagered per visit")]):
        y = v[col] / v[col].iloc[0] * 100 if len(v) else v[col]
        fig3.add_trace(go.Scatter(x=v.month_start, y=y, name=name, mode="lines+markers",
                                  line=dict(color=SERIES[i], width=2), marker=dict(size=8), hovertemplate="%{y:.1f}"))
    fig3.add_hline(y=100, line_color=AXIS, line_width=1)
    fig3.update_layout(yaxis_title_text="Index, first month = 100", xaxis=dict(tickformat="%b", dtick="M1"))
    visits = Chart("demand-visits", "Fewer visits, or smaller ones?", fig3, "mart_visits_month",
                   subtitle="Card holders only, by the month each visit began. Fewer visits call for "
                            "marketing; smaller visits call for the floor itself.",
                   table=table(v, {"month_start": lambda d: f"{d:%B}", "visits": fmt_num, "coin_in": fmt_money,
                                   "per_visit": fmt_money}), note="Not affected by zone or bank.")

    wk = daily.groupby("weekday_index").agg(c=("coin_in", "sum"), md=("machine_days", "sum")).reset_index()
    wk["per_md"] = wk.c / wk.md
    wk["weekday"] = wk.weekday_index.map(lambda i: WEEKDAYS[int(i)])
    fig4 = figure(height=260, legend=False)
    fig4.add_trace(go.Bar(x=wk.weekday.str[:3], y=wk.per_md, marker_color=BLUE, customdata=wk.weekday,
                          hovertemplate="%{customdata}: %{y:$,.0f} per machine-day<extra></extra>"))
    money_axis(fig4, title="Coin-in per machine-day")
    weekday = Chart("demand-weekday", "Demand by day of the week", fig4, "mart_machine_daily",
                    subtitle="The weekly rhythm the forecast in chapter 6 is built on.",
                    table=table(wk[["weekday", "per_md"]], {"per_md": fmt_money}), wide=True)

    w, p = f.where(location=False)
    fm = query(f"""SELECT machine_id, arg_max(x_m, gaming_date) x, arg_max(y_m, gaming_date) y,
                          arg_max(zone_id, gaming_date) zone_id, arg_max(zone_name, gaming_date) zone_name,
                          arg_max(bank_id, gaming_date) bank_id,
                          SUM(theo_usd) / NULLIF(SUM(available_seconds) / 3600.0, 0) theo_per_hr
                   FROM {T('mart_machine_daily')} WHERE {w} GROUP BY machine_id""", p).dropna(subset=["x", "y"])
    fig5 = figure(height=440, legend=False)
    sel = (fm.zone_id == f.zone) & ((fm.bank_id == f.bank) if f.bank else True) if f.zone else pd.Series(True, index=fm.index)
    for mask, op in [(~sel, 0.18), (sel, 1)]:
        d = fm[mask]
        if d.empty:
            continue
        fig5.add_trace(go.Scatter(
            x=d.x, y=d.y, mode="markers", opacity=op,
            marker=dict(color=d.theo_per_hr, colorscale=SEQ_BLUE, cmin=fm.theo_per_hr.min(),
                        cmax=fm.theo_per_hr.max(), size=12, symbol="square", line=dict(color=SURFACE, width=1),
                        showscale=bool(op == 1),
                        colorbar=dict(title=dict(text="Theo / open hr", side="right"), tickprefix="$",
                                      outlinewidth=0, thickness=10)),
            customdata=d[["machine_id", "zone_name", "bank_id"]],
            hovertemplate="<b>%{customdata[0]}</b>, %{customdata[1]} bank %{customdata[2]}<br>"
                          "%{marker.color:$,.2f} theo per open hour<extra></extra>"))
    for z, g in fm.groupby("zone_name"):
        fig5.add_annotation(x=g.x.mean(), y=g.y.max() + 4, text=z, showarrow=False,
                            font=dict(size=11, color=INK_2), yanchor="bottom")
    fig5.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"),
                       margin=dict(l=4, r=4, t=8, b=4))
    floor_map = Chart("demand-map", "The floor, by expected win per open hour", fig5,
                      "mart_machine_daily (x_m, y_m)",
                      subtitle="Each square is a machine in its slot. Darker squares should earn more for "
                               "every hour they're open.", wide=True)

    wz, pz = f.where(location=False)
    zd = query(f"""SELECT zone_name, date_trunc('week', gaming_date) AS week, COUNT(DISTINCT gaming_date) AS days,
                          SUM(theo_usd) theo, SUM(available_seconds) avail, SUM(entries_observed) entries,
                          SUM(counter_observed_seconds) obs, SUM(counter_expected_seconds) exp
                   FROM {T('mart_zone_daily')} WHERE {wz} GROUP BY 1, 2 ORDER BY 2""", pz)
    zd = _full_weeks(zd[zd.days == 7] if (zd.days == 7).any() else zd, "week", f)
    zd["theo_per_hr"] = zd.theo / (zd.avail / 3600)
    zd["entries_per_hr"] = zd.entries / (zd.obs / 3600).where(zd.obs > 0)
    zd["coverage"] = zd.obs / zd.exp
    zones = sorted(zd.zone_name.unique())
    sel_zone = zone_name(f.zone) if f.zone else None

    def zone_lines(col, fmt, title):
        fg = figure(height=320, hovermode="x unified")
        for i, z in enumerate(zones[:8]):
            d = zd[zd.zone_name == z]
            dim = sel_zone and z != sel_zone
            fg.add_trace(go.Scatter(x=d.week, y=d[col], name=z, mode="lines",
                                    line=dict(color=MUTED if dim else SERIES[i], width=1 if dim else 2),
                                    opacity=0.5 if dim else 1, hovertemplate=fmt))
        fg.update_layout(yaxis_title_text=title)
        return fg

    fz = zone_lines("theo_per_hr", "%{y:$,.2f}", "Theo per open hour")
    fz.update_layout(yaxis_tickprefix="$")
    zone_demand = Chart("demand-zones", "Week by week, zone by zone", fz, "mart_zone_daily",
                        subtitle="Full weeks only. Pick a zone in the filter to light it up.",
                        table=table(zd[["zone_name", "week", "theo_per_hr", "entries_per_hr", "coverage"]],
                                    {"week": lambda d: f"{d:%b %d}", "theo_per_hr": lambda x: fmt_money(x, 2),
                                     "entries_per_hr": lambda x: fmt_num(x, 1), "coverage": fmt_pct}))
    traffic = Chart("demand-traffic", "Foot traffic by zone", zone_lines("entries_per_hr", "%{y:,.1f}",
                                                                          "Entries per counter hour"),
                    "mart_zone_daily",
                    subtitle="Door counts, not unique visitors, and seated players aren't counted. Hours with "
                             "the counter offline are left out, not counted as zero.")

    k = floor_kpis(f)
    first_last = mon.iloc[[0, -1]] if len(mon) > 1 else None
    change = (first_last.c.iloc[1] / first_last.md.iloc[1]) / (first_last.c.iloc[0] / first_last.md.iloc[0]) - 1 \
        if first_last is not None else None
    best = wk.sort_values("per_md").iloc[-1] if len(wk) else None
    return {
        "headline": demand_story(f),
        "lede": "Demand is coin-in per machine-day, so adding, removing or breaking machines doesn't "
                "masquerade as a change in players. Outside benchmarks separate a market-wide swing "
                "from one that's ours.",
        "rail": [
            tile("Coin-in per machine-day", fmt_money(k["coin_in"] / k["machine_days"] if k["machine_days"] else None),
                 f.period_label),
            tile("First to last month", fmt_pct(change, 1) if change is not None else "–",
                 "Monthly average", "pos" if (change or 0) >= 0 else "neg"),
            tile("Busiest day", best.weekday if best is not None else "–",
                 f"{fmt_money(best.per_md)} per machine-day" if best is not None else ""),
            tile("Carded share of play", fmt_pct(k["carded"] / k["coin_in"] if k["coin_in"] else None),
                 "Coin-in on a loyalty card"),
            tile("Event days", str(int(daily.events_active.notna().sum())), "In the period"),
        ],
        "sections": [{"charts": [trend, bench, visits, floor_map, zone_demand, traffic, weekday]}],
        "meaning": "If the floor moved with Missouri and Las Vegas, the cause is the season or the city, "
                   "and no floor change will fix it. A quiet zone that stays quiet while others move is "
                   "a location problem the budget can act on.",
    }


# =========================================================================================
# 4 · Downtime (Q3)
# =========================================================================================
def _downtime(f: Filters) -> pd.DataFrame:
    w, p = f.where()
    dh = query(f"""SELECT gaming_date, local_hour, machine_id, zone_id, bank_id, manufacturer,
                          downtime_seconds, fault_downtime_seconds, planned_downtime_seconds,
                          estimated_lost_theo_usd, lost_theo_low_usd, lost_theo_high_usd, hidden_downtime_flag
                   FROM {T('mart_downtime_hourly')}
                   WHERE {w} AND (downtime_seconds > 0 OR hidden_downtime_flag)""", p)
    dh["weekday"] = pd.to_datetime(dh.gaming_date).dt.day_name()
    dh["shift"] = dh.local_hour.map(shift_of)
    return dh


def _tickets(f: Filters) -> pd.DataFrame:
    w, p = f.where(location=False, alias="t")      # location is filtered after the join
    t = query(f"""SELECT t.*, d.zone_id, d.zone_name, d.bank_id, d.manufacturer
                  FROM {T('mart_tickets')} t
                  LEFT JOIN {T('mart_machine_daily')} d USING (machine_id, gaming_date)
                  WHERE {w}""", p)
    local = pd.to_datetime(t.opened_at_utc).dt.tz_localize("UTC").dt.tz_convert("America/Los_Angeles")
    t["shift"] = local.dt.hour.map(shift_of)
    t["type"] = t.event_type.map(lambda e: EVENT_TYPES.get(e, e))
    return t


def downtime_story(f: Filters, dh: pd.DataFrame | None = None) -> str:
    dh = _downtime(f) if dh is None else dh
    lost = dh.estimated_lost_theo_usd.sum()
    if not lost:
        return "No downtime was recorded in this selection."
    by_shift = dh.groupby("shift").estimated_lost_theo_usd.sum()
    peak = dh.groupby(["weekday", "local_hour"]).estimated_lost_theo_usd.sum().idxmax()
    return (f"Downtime cost an estimated {fmt_short_money(lost)} in expected win "
            f"({fmt_short_money(dh.lost_theo_low_usd.sum())} to {fmt_short_money(dh.lost_theo_high_usd.sum())}). "
            f"The {by_shift.idxmax().lower()} shift carries {by_shift.max() / lost:.0%} of it, and "
            f"{peak[0]}s around {_hour_label(int(peak[1]))} are the costliest hour of the week.")


def downtime(f: Filters) -> dict:
    dh = _downtime(f)
    t = _tickets(f)
    if f.zone:
        t = t[t.zone_id == f.zone]
    if f.bank:
        t = t[t.bank_id == f.bank]
    faults = t[t.controllable_fault.fillna(False).astype(bool)]

    hours = list(range(6, 24)) + list(range(0, 6))      # gaming day runs 6 a.m. to 6 a.m.
    hm = dh.groupby(["weekday", "local_hour"]).estimated_lost_theo_usd.sum().unstack("local_hour") \
        .reindex(index=_ordered(dh.weekday, WEEKDAYS), columns=hours).fillna(0)
    fig = figure(height=320, legend=False)
    fig.add_trace(go.Heatmap(z=hm.values, x=[_hour_label(h) for h in hours], y=hm.index, colorscale=SEQ_BLUE,
                             xgap=2, ygap=2,
                             colorbar=dict(title=dict(text="Lost theo", side="right"), tickprefix="$",
                                           tickformat="~s", outlinewidth=0, thickness=10),
                             hovertemplate="%{y}, %{x}<br>Lost theo %{z:$,.0f}<extra></extra>"))
    fig.update_layout(xaxis=dict(showgrid=False, linecolor="rgba(0,0,0,0)", ticks="", tickangle=0, dtick=3,
                                 type="category"),
                      yaxis=dict(showgrid=False, autorange="reversed"))
    heat = Chart("downtime-heat", "When outages cost the most", fig, "mart_downtime_hourly",
                 subtitle="Expected win lost while machines were down, by gaming day and hour. The gaming "
                          "day runs 6 a.m. to 6 a.m., so late-night hours belong to the evening before. "
                          "Stronger color means more play lost.",
                 table=table(hm.reset_index().melt(id_vars="weekday", var_name="hour", value_name="lost_theo_usd"),
                             {"lost_theo_usd": fmt_money}), wide=True)

    dh["month"] = pd.to_datetime(dh.gaming_date).dt.to_period("M").dt.start_time
    mo = dh.groupby("month")[["estimated_lost_theo_usd", "lost_theo_low_usd", "lost_theo_high_usd"]].sum().reset_index()
    fig2 = figure(height=300, legend=False)
    fig2.add_trace(go.Bar(x=mo.month, y=mo.estimated_lost_theo_usd, marker_color=BLUE,
                          error_y=dict(type="data", symmetric=False,
                                       array=mo.lost_theo_high_usd - mo.estimated_lost_theo_usd,
                                       arrayminus=mo.estimated_lost_theo_usd - mo.lost_theo_low_usd,
                                       color=INK_2, thickness=1.5, width=4),
                          hovertemplate="%{x|%B}: %{y:$,.0f}<extra></extra>"))
    money_axis(fig2, title="Lost theo")
    fig2.update_layout(xaxis=dict(tickformat="%b", dtick="M1"))
    by_month = Chart("downtime-month", "Lost play by month", fig2, "mart_downtime_hourly",
                     subtitle="Whiskers show the estimate's range from the fake-outage test.",
                     table=table(mo, {"month": lambda v: f"{v:%B}", "estimated_lost_theo_usd": fmt_money,
                                      "lost_theo_low_usd": fmt_money, "lost_theo_high_usd": fmt_money}))

    mf = dh.groupby("manufacturer").agg(lost=("estimated_lost_theo_usd", "sum"), low=("lost_theo_low_usd", "sum"),
                                        high=("lost_theo_high_usd", "sum"), hrs=("downtime_seconds", "sum"),
                                        machines=("machine_id", "nunique")).reset_index().sort_values("lost")
    mf["hrs"] /= 3600
    fig3 = figure(height=300, legend=False)
    fig3.add_trace(go.Scatter(x=mf.lost, y=mf.manufacturer, mode="markers",
                              marker=dict(color=BLUE, size=11, line=dict(color=SURFACE, width=2)),
                              error_x=dict(type="data", symmetric=False, array=mf.high - mf.lost,
                                           arrayminus=mf.lost - mf.low, color=BLUE, thickness=2, width=6),
                              customdata=mf[["low", "high", "hrs", "machines"]],
                              hovertemplate="<b>%{y}</b><br>Lost theo %{x:$,.0f}<br>Range %{customdata[0]:$,.0f} "
                                            "to %{customdata[1]:$,.0f}<br>%{customdata[2]:,.0f} hours down across "
                                            "%{customdata[3]} machines<extra></extra>"))
    money_axis(fig3, "xaxis", "Lost theo")
    fig3.update_layout(xaxis=dict(showgrid=True, gridcolor=GRID, rangemode="tozero"), yaxis=dict(showgrid=False))
    by_mfr = Chart("downtime-mfr", "By manufacturer", fig3, "mart_downtime_hourly",
                   subtitle="If one maker dominates, preventive maintenance for that maker is the fix.",
                   table=table(mf, {"lost": fmt_money, "low": fmt_money, "high": fmt_money, "hrs": fmt_num}))

    shifts = [s for s, *_ in SHIFTS]
    rs = faults.groupby("shift").agg(tickets=("operation_id", "count"), response=("response_hours", "median"),
                                     repair=("repair_hours", "median")).reindex(shifts).reset_index()
    lost_shift = dh.groupby("shift").estimated_lost_theo_usd.sum().reindex(shifts)
    fig4 = figure(height=300, barmode="group")
    fig4.add_trace(go.Bar(x=rs["shift"], y=rs.response * 60, name="Waiting for a technician", marker_color=SERIES[0],
                          hovertemplate="%{x}: %{y:.0f} min to start work<extra></extra>"))
    fig4.add_trace(go.Bar(x=rs["shift"], y=rs.repair * 60, name="Repair itself", marker_color=SERIES[1],
                          hovertemplate="%{x}: %{y:.0f} min to repair<extra></extra>"))
    fig4.update_layout(yaxis_title_text="Median minutes per fault")
    response = Chart("downtime-response", "Slow to respond, or slow to fix?", fig4, "mart_tickets",
                     subtitle="A long wait points to staffing (add a technician). A long repair points to the "
                              "machines (preventive maintenance).",
                     table=table(rs.assign(lost_theo=rs["shift"].map(lost_shift)),
                                 {"response": lambda v: fmt_num(v, 2), "repair": lambda v: fmt_num(v, 2),
                                  "lost_theo": fmt_money}))

    tc = t.groupby("type").size().sort_values()
    fig5 = figure(height=300, legend=False)
    fig5.add_trace(go.Bar(y=tc.index, x=tc.values, orientation="h",
                          marker_color=[BLUE if ty == EVENT_TYPES["fault_repair"] else MUTED for ty in tc.index],
                          hovertemplate="%{y}: %{x} tickets<extra></extra>"))
    fig5.update_layout(xaxis=dict(showgrid=True, gridcolor=GRID, title_text="Tickets"), yaxis=dict(showgrid=False))
    kinds = Chart("downtime-kinds", "What kind of downtime", fig5, "mart_tickets",
                  subtitle="Only fault repairs (in blue) are something a technician or maintenance can cut.",
                  table=table(tc.rename("Tickets").rename_axis("Type").reset_index()))

    wk = faults.assign(week=pd.to_datetime(faults.gaming_date).dt.to_period("W-SUN").dt.start_time) \
        .groupby("week").size().rename("faults").reset_index()
    wk = _full_weeks(wk, "week", f)
    fig6 = figure(height=260, legend=False, hovermode="x unified")
    fig6.add_trace(go.Scatter(x=wk.week, y=wk.faults, mode="lines+markers", line=dict(color=BLUE, width=2),
                              marker=dict(size=7), hovertemplate="Week of %{x|%b %d}: %{y} faults<extra></extra>"))
    fig6.update_layout(yaxis=dict(title_text="Fault repairs per week", rangemode="tozero"))
    weekly = Chart("downtime-weekly", "Faults week by week", fig6, "mart_tickets",
                   subtitle="A steady climb suggests wear; a single spike suggests one event.", wide=True)

    top = dh.groupby(["machine_id", "manufacturer"]).agg(
        down=("downtime_seconds", "sum"), hidden=("hidden_downtime_flag", "sum"),
        lost=("estimated_lost_theo_usd", "sum")).reset_index().sort_values("lost", ascending=False).head(15)
    top = top.merge(positions()[["machine_id", "zone_name"]], on="machine_id", how="left")
    top_t = pd.DataFrame({"Machine": top.machine_id, "Zone": top.zone_name, "Maker": top.manufacturer,
                          "Hours down": top.down / 3600, "Hidden-downtime hours": top.hidden, "Lost theo": top.lost})
    return {
        "headline": downtime_story(f, dh),
        "lede": "Lost play is valued in theo, the win the house expected, using neighbours in the same "
                "zone and hour as the yardstick. A lucky or unlucky stretch can't inflate it.",
        "rail": [
            tile("Lost theo", fmt_short_money(dh.estimated_lost_theo_usd.sum()),
                 f"{fmt_short_money(dh.lost_theo_low_usd.sum())} to {fmt_short_money(dh.lost_theo_high_usd.sum())}"),
            tile("Machine-hours down", fmt_num(dh.downtime_seconds.sum() / 3600), f.period_label),
            tile("Hidden-downtime hours", fmt_num(dh.hidden_downtime_flag.sum()),
                 "Open, idle, neighbours busy"),
            tile("Fault repairs", fmt_num(len(faults)), f"{plural(len(t), 'ticket')} in all"),
            tile("Median wait, then fix", f"{fmt_num(faults.response_hours.median() * 60)} + "
                                          f"{fmt_num(faults.repair_hours.median() * 60)} min", "Per fault"),
        ],
        "sections": [
            {"charts": [heat, by_month, by_mfr, response, kinds, weekly]},
            {"title": "Machines losing the most play", "source": "mart_downtime_hourly",
             "blocks": [table(top_t, {"Hours down": lambda v: fmt_num(v, 1), "Lost theo": fmt_money},
                              {"Machine": lambda r: machine_link(f)(r.Machine)})]},
        ],
        "meaning": "If one shift waits longest, a technician on that shift buys back the most play. If one "
                   "manufacturer breaks most, maintenance for that maker does. Hidden-downtime hours are "
                   "leads to check, not counted losses.",
        "scope_note": "Hidden downtime is a candidate flag and isn't added to measured losses. "
                      "Hours where no estimate was possible are left out of the totals rather than counted as zero.",
    }


# =========================================================================================
# 5 · Players and comps (Q4, Q5)
# =========================================================================================
def _player_totals(f: Filters) -> dict:
    w, p = f.where_month(guests=True)
    r = query(f"""
        WITH p AS (SELECT player_id, SUM(actual_tracked_loss_usd) loss, SUM(theo_usd) theo,
                          BOOL_OR(above_expected_loss_flag) heavy
                   FROM {T('mart_player_month')} WHERE {w} GROUP BY player_id)
        SELECT COUNT(*) players, SUM(CASE WHEN loss < 0 THEN 1 ELSE 0 END) winners, SUM(loss) loss,
               SUM(theo) theo, SUM(CASE WHEN heavy THEN 1 ELSE 0 END) heavy FROM p""", p).iloc[0].to_dict()
    curve = query(f"""
        WITH p AS (SELECT player_id, SUM(actual_tracked_loss_usd) loss FROM {T('mart_player_month')}
                   WHERE {w} GROUP BY player_id),
             r AS (SELECT ROW_NUMBER() OVER (ORDER BY loss DESC) rn, COUNT(*) OVER () n,
                          SUM(loss) OVER () total,
                          SUM(loss) OVER (ORDER BY loss DESC ROWS UNBOUNDED PRECEDING) cum FROM p)
        SELECT CEIL(100.0 * rn / n)::INT pct, arg_max(cum, rn) / any_value(total) AS "share"
        FROM r GROUP BY 1 ORDER BY 1""", p)
    r["curve"] = curve
    share = curve.set_index("pct").share
    r["top1"], r["top10"] = share.get(1), share.get(10)
    return r


def guests_story(f: Filters, tot: dict | None = None) -> str:
    tot = _player_totals(f) if tot is None else tot
    if not tot["players"]:
        return "No card holders match this selection."
    diff = tot["loss"] - tot["theo"]
    return (f"Card holders lost {fmt_short_money(tot['loss'])} against an expected {fmt_short_money(tot['theo'])}, "
            f"so luck ran {fmt_short_money(abs(diff))} in the {'house' if diff > 0 else 'players'}' favour. "
            f"The top 10% of players produced {fmt_pct(tot['top10'], 0)} of the house's net win, and "
            f"{tot['winners'] / tot['players']:.0%} of players came out ahead.")


def comps_story(f: Filters, ct: pd.DataFrame) -> str:
    ct = ct.assign(per_loss=ct.comp_cost_usd / ct.actual_tracked_loss_usd.where(ct.actual_tracked_loss_usd > 0),
                   per_coin=ct.comp_cost_usd / ct.tracked_coin_in_usd.where(ct.tracked_coin_in_usd > 0))
    cand = ct[ct.policy_change_candidate.fillna(False).astype(bool)]
    tot = ct[["comp_cost_usd", "actual_tracked_loss_usd", "tracked_coin_in_usd"]].sum()
    base = (f"Comps cost {100 * tot.comp_cost_usd / tot.actual_tracked_loss_usd:.1f}¢ for every $1 players lost "
            f"and {100 * tot.comp_cost_usd / tot.tracked_coin_in_usd:.2f}¢ per $1 wagered.")
    if cand.empty:
        return base + " No change shows up in both measures, so nothing points to a policy shift."
    c = cand.iloc[0]
    g = ct[ct.opening_tier == c.opening_tier]
    before, after = g[g.month_start < c.month_start], g[g.month_start >= c.month_start]
    if before.empty or after.empty:
        return base
    r = lambda d, num, den: d[num].sum() / d[den].sum()
    b_l, a_l = r(before, "comp_cost_usd", "actual_tracked_loss_usd"), r(after, "comp_cost_usd", "actual_tracked_loss_usd")
    b_c, a_c = r(before, "comp_cost_usd", "tracked_coin_in_usd"), r(after, "comp_cost_usd", "tracked_coin_in_usd")
    both = (a_l > b_l) == (a_c > b_c)
    return (f"{c.opening_tier} comps went from {100 * b_l:.1f}¢ to {100 * a_l:.1f}¢ per $1 lost after "
            f"{pd.Timestamp(c.month_start):%B}, and per $1 wagered moved {'the same way' if both else 'the other way'} "
            f"({100 * b_c:.2f}¢ to {100 * a_c:.2f}¢). "
            + ("That looks like a policy change, not luck." if both else "That looks like luck in players' results, not a policy change."))


def guests(f: Filters) -> dict:
    tot = _player_totals(f)
    w, p = f.where_month(guests=True)
    mon = query(f"""SELECT month_start, COUNT(*) player_months, SUM(tracked_coin_in_usd) coin_in,
                           SUM(tracked_payout_usd) payout, SUM(actual_tracked_loss_usd) loss, SUM(theo_usd) theo,
                           SUM(CASE WHEN winner_flag THEN 1 ELSE 0 END) winners
                    FROM {T('mart_player_month')} WHERE {w} GROUP BY 1 ORDER BY 1""", p)
    mon["winner_share"] = mon.winners / mon.player_months

    fig = figure(height=320, hovermode="x unified")
    fig.add_trace(go.Scatter(x=mon.month_start, y=mon.theo, name="Expected loss (theo)", mode="lines+markers",
                             line=dict(color=MUTED, width=2), marker=dict(size=8), hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=mon.month_start, y=mon.loss, name="Actual loss", mode="lines+markers",
                             line=dict(color=BLUE, width=2), marker=dict(size=8), hovertemplate="%{y:$,.0f}"))
    money_axis(fig, title="Players' net loss")
    fig.update_layout(xaxis=dict(tickformat="%b", dtick="M1"))
    trend = Chart("guests-trend", f"What players lost, against what the math expected", fig,
                  "mart_player_month", wide=True,
                  subtitle="The gap between the lines is luck, month by month.",
                  table=table(mon, {"month_start": lambda v: f"{v:%B}", "coin_in": fmt_money, "payout": fmt_money,
                                    "loss": fmt_money, "theo": fmt_money, "winner_share": fmt_pct,
                                    "player_months": fmt_num, "winners": fmt_num}))

    def seg_bar(col, field, order, cid, title):
        sw, sp = f.where_month(guests=True, skip=(field,))
        g = query(f"""SELECT {col} seg, SUM(actual_tracked_loss_usd) loss, COUNT(DISTINCT player_id) players,
                             SUM(actual_tracked_loss_usd) / COUNT(*) per_pm
                      FROM {T('mart_player_month')} WHERE {sw} GROUP BY 1""", sp)
        g = g.set_index("seg").reindex(_ordered(g.seg, order)).reset_index()
        chosen = getattr(f, field)
        fg = figure(height=280, legend=False)
        fg.add_trace(go.Bar(x=g.seg, y=g.per_pm,
                            marker_color=[BLUE if not chosen or v == chosen else MUTED for v in g.seg],
                            customdata=g.players,
                            hovertemplate="%{x}: %{y:$,.0f} lost per player-month<br>%{customdata:,} players"
                                          "<extra></extra>"))
        money_axis(fg, title="Loss per player-month")
        fg.update_layout(xaxis=dict(type="category"))
        return Chart(cid, title, fg, "mart_player_month", third=True,
                     table=table(g, {"loss": fmt_money, "players": fmt_num, "per_pm": fmt_money}))

    by_tier = seg_bar("opening_tier", "tier", TIER_ORDER, "guests-tier", "By opening tier")
    by_age = seg_bar("age_band", "age_band", ["21-34", "35-49", "50-64", "65+", "Unknown"], "guests-age", "By age band")
    by_home = seg_bar("home_region", "home_region", ["Local", "Regional", "Domestic", "International"],
                      "guests-home", "By home region")

    cv = tot["curve"]
    fig2 = figure(height=320)
    fig2.add_trace(go.Scatter(x=[0, 100], y=[0, 1], mode="lines", name="Every player equal",
                              line=dict(color=MUTED, width=1), hoverinfo="skip"))
    fig2.add_trace(go.Scatter(x=pd.concat([pd.Series([0]), cv.pct]), y=pd.concat([pd.Series([0.0]), cv.share]),
                              mode="lines", name="Actual", line=dict(color=BLUE, width=2),
                              hovertemplate="Top %{x}% of players: %{y:.0%} of net win<extra></extra>"))
    pct_axis(fig2, title="Share of the house's net win")
    fig2.update_layout(xaxis=dict(ticksuffix="%", title_text="Players, biggest losers first"))
    conc = Chart("guests-conc", "How concentrated the losses are", fig2, "mart_player_month",
                 subtitle="Summed per player across the selected months first. The curve can pass 100% "
                          "because players who won pull the total back down.",
                 table=table(cv, {"share": fmt_pct}))

    fig3 = figure(height=280, legend=False)
    fig3.add_trace(go.Scatter(x=mon.month_start, y=mon.winner_share, mode="lines+markers",
                              line=dict(color=BLUE, width=2), marker=dict(size=8),
                              hovertemplate="%{x|%B}: %{y:.1%} ended the month ahead<extra></extra>"))
    pct_axis(fig3, title="Players ahead for the month")
    fig3.update_layout(xaxis=dict(tickformat="%b", dtick="M1"), yaxis_rangemode="tozero")
    ahead = Chart("guests-ahead", "Who walks away ahead", fig3, "mart_player_month")

    # ---- Q5: comps -----------------------------------------------------------------------
    wc, pc = f.where_month()
    if f.tier:
        wc, pc = wc + " AND opening_tier = ?", pc + [f.tier]
    ct = query(f"SELECT * FROM {T('mart_comps_tier_month')} WHERE {wc} ORDER BY month_start", pc)
    wd, pd_ = f.where(location=False)
    cd = query(f"SELECT * FROM {T('mart_comps_daily')} WHERE {wd} ORDER BY gaming_date", pd_)
    roll = lambda s: s.rolling(7, min_periods=1).sum()
    cd["per_loss7"] = roll(cd.comp_cost_usd) / roll(cd.actual_tracked_loss_usd).where(lambda s: s > 0)
    cd["per_coin7"] = roll(cd.comp_cost_usd) / roll(cd.tracked_coin_in_usd).where(lambda s: s > 0)
    changes = cd[cd.policy_change_candidate.fillna(False).astype(bool)].gaming_date

    def rate_chart(col, cid, title, axis, sub):
        fg = figure(height=260, legend=False, hovermode="x unified")
        for dte in changes:
            fg.add_vline(x=dte, line_color=ORANGE, line_width=1.5)
            fg.add_annotation(x=dte, y=1, yref="paper", text="Candidate change", showarrow=False,
                              xanchor="left", yanchor="top", xshift=4, font=dict(size=10, color=INK_2))
        fg.add_trace(go.Scatter(x=cd.gaming_date, y=cd[col] * 100, mode="lines", line=dict(color=BLUE, width=2),
                                hovertemplate="%{y:.2f}¢<extra></extra>"))
        fg.update_layout(yaxis=dict(title_text=axis, ticksuffix="¢"))
        return Chart(cid, title, fg, "mart_comps_daily", subtitle=sub)

    per_loss = rate_chart("per_loss7", "comps-loss", "Comp cost per $1 players lost", "Cents, 7-day",
                          "The headline rate. It swings with players' luck, so read it with the chart beside it.")
    per_coin = rate_chart("per_coin7", "comps-coin", "Comp cost per $1 wagered", "Cents, 7-day",
                          "Steadier, because wagers don't depend on luck. A change in both is a real change.")

    tiers = _ordered(ct.opening_tier, TIER_ORDER)
    fig4 = figure(height=300, hovermode="x unified")
    for i, tr in enumerate(tiers[:8]):
        g = ct[ct.opening_tier == tr]
        dim = f.tier and tr != f.tier
        fig4.add_trace(go.Scatter(x=g.month_start, y=100 * g.comp_cost_usd / g.actual_tracked_loss_usd.where(g.actual_tracked_loss_usd > 0),
                                  name=tr, mode="lines+markers",
                                  line=dict(color=MUTED if dim else SERIES[i], width=2), marker=dict(size=8),
                                  hovertemplate="%{y:.1f}¢"))
        flagged = g[g.policy_change_candidate.fillna(False).astype(bool)]
        if not flagged.empty:
            fig4.add_trace(go.Scatter(x=flagged.month_start,
                                      y=100 * flagged.comp_cost_usd / flagged.actual_tracked_loss_usd,
                                      mode="markers", name=f"{tr}: candidate change", showlegend=False,
                                      marker=dict(symbol="diamond-open", size=16, color=ORANGE, line=dict(width=2)),
                                      hoverinfo="skip"))
    fig4.update_layout(yaxis=dict(title_text="Cents per $1 lost", ticksuffix="¢"),
                       xaxis=dict(tickformat="%b", dtick="M1"))
    tier_rate = Chart("comps-tier", "By opening tier", fig4, "mart_comps_tier_month",
                      subtitle="Players stay in the tier they opened the year in, so each line is a fixed group. "
                               "Diamonds mark candidate changes.",
                      table=table(ct[["opening_tier", "month_start", "active_players", "comp_cost_usd",
                                      "actual_tracked_loss_usd", "tracked_coin_in_usd", "comp_cost_per_actual_loss",
                                      "comp_cost_per_coin_in", "policy_change_candidate"]],
                                  {"month_start": lambda v: f"{v:%b}", "comp_cost_usd": fmt_money,
                                   "actual_tracked_loss_usd": fmt_money, "tracked_coin_in_usd": fmt_money,
                                   "comp_cost_per_actual_loss": lambda v: fmt_pct(v, 1),
                                   "comp_cost_per_coin_in": lambda v: fmt_pct(v, 2), "active_players": fmt_num}))

    pts = ct.groupby("month_start").agg(earned=("points_earned", "sum"), redeemed=("points_redeemed", "sum"),
                                        balance=("points_balance_end", "sum")).reset_index()
    fig5 = figure(height=300, barmode="group")
    fig5.add_trace(go.Bar(x=pts.month_start, y=pts.earned, name="Earned", marker_color=SERIES[0],
                          hovertemplate="%{y:,.0f} earned<extra></extra>"))
    fig5.add_trace(go.Bar(x=pts.month_start, y=pts.redeemed, name="Redeemed", marker_color=SERIES[1],
                          hovertemplate="%{y:,.0f} redeemed<extra></extra>"))
    fig5.update_layout(yaxis=dict(tickformat="~s", title_text="Points"), xaxis=dict(tickformat="%b", dtick="M1"))
    points = Chart("comps-points", "Points earned and redeemed", fig5, "mart_comps_tier_month",
                   subtitle="Unredeemed points are a future cost, counted here in points, not dollars.",
                   table=table(pts, {"month_start": lambda v: f"{v:%B}", "earned": fmt_num, "redeemed": fmt_num,
                                     "balance": fmt_num}))

    wf, pf = f.where(location=False)
    carded = query(f"SELECT SUM(carded_coin_in_usd) / SUM(coin_in_usd) FROM {T('mart_machine_daily')} WHERE {wf}", pf).iloc[0, 0]
    ctot = ct[["comp_cost_usd", "actual_tracked_loss_usd", "tracked_coin_in_usd"]].sum()
    last_bal = ct.sort_values("month_start").groupby("opening_tier").points_balance_end.last().sum()
    has = bool(tot["players"])
    return {
        "headline": guests_story(f, tot),
        "lede": "These pages see loyalty-card play only, so the totals are smaller than the floor's by "
                "design. Use the guest filters to follow one group through both sections.",
        "rail": [
            tile("Carded share of floor play", fmt_pct(carded), "What these results describe"),
            tile("Wagered", fmt_short_money(mon.coin_in.sum()), f.guest_label),
            tile("Net loss", fmt_short_money(tot["loss"]), f"Expected {fmt_short_money(tot['theo'])}"),
            tile("Players ahead", fmt_pct(tot["winners"] / tot["players"] if has else None, 0),
                 "Over the whole period"),
            tile("Top 10% of players", fmt_pct(tot["top10"], 0), "Share of net win"),
        ],
        "sections": [
            {"title": "Tracked player outcomes", "tag": "Q4",
             "charts": [trend, by_tier, by_age, by_home, conc, ahead],
             "intro": (f"{fmt_num(tot['heavy'])} players lost more than twice their expected loss in at least "
                       "one month. That figure is for protective outreach only, never for marketing."
                       if has else None)},
            {"title": "The comp program", "tag": "Q5", "headline": comps_story(f, ct) if not ct.empty else None,
             "rail": [
                 tile("Comp cost", fmt_short_money(ctot.comp_cost_usd), "Economic cost, counted once"),
                 tile("Per $1 players lost", f"{100 * ctot.comp_cost_usd / ctot.actual_tracked_loss_usd:.1f}¢"
                      if ctot.actual_tracked_loss_usd > 0 else "–", "Headline rate"),
                 tile("Per $1 wagered", f"{100 * ctot.comp_cost_usd / ctot.tracked_coin_in_usd:.2f}¢"
                      if ctot.tracked_coin_in_usd > 0 else "–", "Luck-free check"),
                 tile("Points outstanding", fmt_num(last_bal), "End of period, in points"),
             ],
             "charts": [per_loss, per_coin, tier_rate, points]},
        ],
        "meaning": "Read the comp lines in pairs: a jump in cost per $1 lost alone is players' luck, but "
                   "a jump in cost per $1 wagered too is the program itself. That's the case for a "
                   "controlled comp pilot rather than a floor-wide change.",
        "guest_filters": True,
        "location_filters": False,
        "scope_note": "Monthly figures use whole months that overlap the period. Concentration and "
                      "winner shares are summed per player first, never averaged across months.",
    }


# =========================================================================================
# 6 · Forecast (model)
# =========================================================================================
def _forecast() -> tuple[pd.DataFrame, pd.DataFrame]:
    fc = query(f"SELECT * FROM {T('mart_forecast')} ORDER BY forecast_date")
    ev = fc[fc.evaluation_eligible.fillna(False).astype(bool) & fc.actual_coin_in_usd.notna()].copy()
    ev["model_err"] = (ev.model_prediction_usd - ev.actual_coin_in_usd).abs()
    ev["base_err"] = (ev.baseline_prediction_usd - ev.actual_coin_in_usd).abs()
    return fc, ev


def forecast_story(fc=None, ev=None) -> str:
    if fc is None:
        fc, ev = _forecast()
    test = ev[ev.split == "test"]
    if test.empty:
        return "The holdout hasn't been scored yet."
    m, b = test.model_err.mean(), test.base_err.mean()
    method = str(fc.model_method.dropna().iloc[0]).replace("_", " ") if fc.model_method.notna().any() else "chosen"
    if m < b:
        return (f"On May and June, which it never saw, the {method} forecast missed by {fmt_money(m)} a day "
                f"against {fmt_money(b)} for a flat average: {1 - m / b:.0%} less error.")
    return (f"On May and June the {method} forecast missed by {fmt_money(m)} a day and didn't beat a flat "
            f"average ({fmt_money(b)}). We plan staffing on weekday averages instead.")


def forecast(f: Filters) -> dict:
    fc, ev = _forecast()
    splits = fc.groupby("split", sort=False).agg(start=("forecast_date", "min"), end=("forecast_date", "max"),
                                                 days=("forecast_date", "count"), fit_start=("fit_start", "first"),
                                                 fit_end=("fit_end", "first"), origin=("forecast_origin", "first"),
                                                 frozen=("prediction_frozen_at_utc", "first")).reset_index()
    mae = ev.groupby("split").agg(model=("model_err", "mean"), base=("base_err", "mean"))
    splits = splits.join(mae, on="split")

    fig = figure(height=380, hovermode="x unified")
    for r in splits.itertuples():
        x0 = pd.Timestamp(r.start) - pd.Timedelta(hours=12)
        if r.split == "test":
            fig.add_vrect(x0=x0, x1=pd.Timestamp(r.end) + pd.Timedelta(hours=12), fillcolor=BAND, line_width=0,
                          layer="below")
        if r.Index > 0:
            fig.add_vline(x=x0, line_color=AXIS, line_width=1)
        fig.add_annotation(name="span-label", x=x0, y=1.0, xref="x", yref="paper",
                           text={"train": "Training", "validation": "Model chosen here", "test": "Holdout test",
                                 "future": "July forecast"}.get(r.split, r.split),
                           showarrow=False, xanchor="left", yanchor="top", xshift=4, font=dict(size=11, color=INK_2))
    fig.add_trace(go.Scatter(x=fc.forecast_date, y=fc.baseline_prediction_usd, name="Flat average (baseline)",
                             line=dict(color=SERIES[1], width=2), hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=fc.forecast_date, y=fc.model_prediction_usd, name="Model",
                             line=dict(color=SERIES[0], width=2), hovertemplate="%{y:$,.0f}"))
    fig.add_trace(go.Scatter(x=fc.forecast_date, y=fc.actual_coin_in_usd, name="Actual", mode="lines",
                             line=dict(color=INK, width=1.5), hovertemplate="%{y:$,.0f}"))
    money_axis(fig, title="Daily floor coin-in")
    main = Chart("forecast-main", "Forecasts against what happened", fig, "mart_forecast", wide=True,
                 subtitle="The model was picked on April, refit on January to April, and frozen before "
                          "May and June were scored. Training months carry no published predictions.",
                 table=table(fc[["forecast_date", "split", "actual_coin_in_usd", "model_prediction_usd",
                                 "baseline_prediction_usd"]],
                             {c: fmt_money for c in ["actual_coin_in_usd", "model_prediction_usd",
                                                     "baseline_prediction_usd"]}))

    scored = splits.dropna(subset=["model"])
    fig2 = figure(height=300, barmode="group")
    names = {"validation": "April (selection)", "test": "May–June (test)"}
    fig2.add_trace(go.Bar(x=scored.split.map(names), y=scored.model, name="Model", marker_color=SERIES[0],
                          hovertemplate="%{x}: %{y:$,.0f} a day<extra></extra>"))
    fig2.add_trace(go.Bar(x=scored.split.map(names), y=scored.base, name="Flat average", marker_color=SERIES[1],
                          hovertemplate="%{x}: %{y:$,.0f} a day<extra></extra>"))
    money_axis(fig2, title="Average miss per day (MAE)")
    by_split = Chart("forecast-mae", "Average miss, by period", fig2, "mart_forecast")

    test = ev[ev.split == "test"].assign(weekday=lambda d: d.forecast_date.dt.day_name())
    tw = test.groupby("weekday")[["model_err", "base_err"]].mean().reindex(_ordered(test.weekday, WEEKDAYS)).reset_index()
    fig3 = figure(height=300, barmode="group")
    fig3.add_trace(go.Bar(x=tw.weekday.str[:3], y=tw.model_err, name="Model", marker_color=SERIES[0],
                          customdata=tw.weekday, hovertemplate="%{customdata}: %{y:$,.0f}<extra></extra>"))
    fig3.add_trace(go.Bar(x=tw.weekday.str[:3], y=tw.base_err, name="Flat average", marker_color=SERIES[1],
                          customdata=tw.weekday, hovertemplate="%{customdata}: %{y:$,.0f}<extra></extra>"))
    money_axis(fig3, title="Test-period MAE")
    by_wd = Chart("forecast-weekday", "Where the model earns its keep", fig3, "mart_forecast",
                  subtitle="Days where the blue bar is far shorter are where staffing to the forecast pays.",
                  table=table(tw, {"model_err": fmt_money, "base_err": fmt_money}))

    jul = fc[fc.split == "future"].copy()
    jul["weekday"] = jul.forecast_date.dt.day_name()
    jul["weekend"] = jul.forecast_date.dt.day_of_week >= 4          # Fri, Sat, Sun
    jul["wk"] = (jul.forecast_date - pd.to_timedelta((jul.forecast_date.dt.day_of_week - 4) % 7, unit="D"))
    wkends = jul[jul.weekend].groupby("wk").agg(total=("model_prediction_usd", "sum"), days=("weekday", "count"))
    wkends = wkends[wkends.days == 3]
    soft = wkends.total.idxmin() if not wkends.empty else None
    colors = [ORANGE if (soft is not None and r.weekend and r.wk == soft) else (BLUE if r.weekend else MUTED)
              for r in jul.itertuples()]
    fig4 = figure(height=300, legend=False)
    fig4.add_trace(go.Bar(x=jul.forecast_date, y=jul.model_prediction_usd, marker_color=colors,
                          customdata=jul.weekday, hovertemplate="%{customdata} %{x|%b %d}: %{y:$,.0f}<extra></extra>"))
    money_axis(fig4, title="Forecast coin-in")
    fig4.update_layout(bargap=0.2, barcornerradius=2)
    july = Chart("forecast-july", "July, as the model sees it", fig4, "mart_forecast",
                 subtitle="Weekends in blue; the softest full weekend in orange. That's the one a promotion "
                          "can lift most, and the forecast is the no-action yardstick for every July action.",
                 wide=True)

    gains = (tw.base_err - tw.model_err).fillna(0)
    best_days = list(tw.weekday[gains.sort_values(ascending=False).index[:2]]) if len(tw) else []
    test_mae = mae.loc["test"] if "test" in mae.index else None
    proto = splits[["split", "start", "end", "days", "fit_start", "fit_end", "origin", "frozen", "model", "base"]]
    proto.columns = ["Split", "From", "To", "Days", "Fit from", "Fit to", "Forecast made", "Frozen (UTC)",
                     "Model MAE", "Baseline MAE"]
    dfmt = lambda v: f"{v:%b %d}" if pd.notna(v) else "–"
    return {
        "headline": forecast_story(fc, ev),
        "lede": "We forecast daily floor coin-in from calendar facts known in advance: weekday, holidays "
                "and events announced before the date. The yardstick is a flat average of the training days.",
        "rail": [
            tile("Model, May–June", fmt_money(test_mae.model) if test_mae is not None else "–", "Average miss per day"),
            tile("Flat average", fmt_money(test_mae.base) if test_mae is not None else "–", "Average miss per day"),
            tile("Less error", fmt_pct(1 - test_mae.model / test_mae.base, 0) if test_mae is not None else "–",
                 "On days it never saw", "pos" if test_mae is not None and test_mae.model < test_mae.base else "neg"),
            tile("July forecast", fmt_short_money(jul.model_prediction_usd.sum()), "No-action baseline"),
            tile("Softest weekend", f"{soft:%b} {soft.day}" if soft is not None else "–", "Promotion pick"),
        ],
        "sections": [
            {"charts": [main, by_split, by_wd, july]},
            {"title": "How it was validated", "source": "mart_forecast",
             "blocks": [table(proto, {"From": dfmt, "To": dfmt, "Fit from": dfmt, "Fit to": dfmt,
                                      "Forecast made": dfmt,
                                      "Frozen (UTC)": lambda v: f"{v:%b %d %H:%M}" if pd.notna(v) else "–",
                                      "Model MAE": fmt_money, "Baseline MAE": fmt_money}, sortable=False)]},
        ],
        "meaning": (f"Staff the added technician to the forecast on {' and '.join(best_days)}, where the "
                    f"model beats the flat average most. Run the promotion on the softest weekend"
                    f"{f' ({soft:%B} {soft.day})' if soft is not None else ''}, not a busy one."
                    if best_days else "Without a scored holdout, plan on weekday averages."),
        "no_filters": True,
        "scope_note": "A fixed holdout, so the filters don't apply here.",
    }


# =========================================================================================
# 7 · The $100K plan (Q6)
# =========================================================================================
def _actions() -> pd.DataFrame:
    a = query(f"SELECT * FROM {T('mart_actions')} WHERE selected ORDER BY proposal_line_id")
    cat = action_catalog().set_index("action_type_id") if not action_catalog().empty else None
    a["name"] = a.action_type_id.map(lambda i: ACTION_SHORT.get(i, i))
    a["full_name"] = a.action_type_id.map(lambda i: cat.name.get(i, i) if cat is not None else i)
    return a


def _evidence_links(refs: str, f: Filters) -> Markup:
    seen, out = set(), []
    for ref in str(refs or "").replace(",", ";").split(";"):
        ep = MART_CHAPTER.get(ref.strip())
        if ep and ep not in seen:
            seen.add(ep)
            title = next(t for e, t, *_ in CHAPTERS if e == ep)
            href = ("/" + ep if ep != "verdict" else "/verdict") + f.qs()
            out.append(f'<a href="{href}">{CHAPTER_NUM[ep]}. {html.escape(title)}</a>')
    return Markup(", ".join(out) or "–")


def plan_story(a: pd.DataFrame | None = None) -> str:
    a = _actions() if a is None else a
    if a.empty:
        return f"Keep the full {fmt_money(BUDGET)}: no action has evidence strong enough to fund yet."
    spent = a.total_cost_usd.sum()
    types = a.action_type_id.nunique()
    net, half = a.net_benefit_usd.sum(min_count=1), a.half_effect_net_benefit_usd.sum(min_count=1)
    s = f"Fund {plural(types, 'action type')} for {fmt_money(spent)} and keep {fmt_money(BUDGET - spent)}."
    if pd.notna(net):
        s += (f" Expected net benefit is {fmt_money(net)}; at half the assumed effect the plan "
              f"{'still nets' if half >= 0 else 'would lose'} {fmt_money(abs(half))}.")
    return s


def plan(f: Filters) -> dict:
    a = _actions()
    spent = a.total_cost_usd.sum()
    kept = BUDGET - spent
    by = a.groupby(["action_type_id", "name", "full_name"], sort=False).agg(
        lines=("proposal_line_id", "count"), qty=("quantity", "sum"), cost=("total_cost_usd", "sum"),
        net=("net_benefit_usd", lambda s: s.sum(min_count=1)), low=("benefit_low_usd", lambda s: s.sum(min_count=1)),
        high=("benefit_high_usd", lambda s: s.sum(min_count=1)),
        half=("half_effect_net_benefit_usd", lambda s: s.sum(min_count=1)),
        lead=("lead_days", "max"), days=("effective_operating_days", "max"), down=("action_downtime_hours", "sum"),
        targets=("target_id", lambda s: ", ".join(map(str, s))), target_type=("target_type", "first"),
        metric=("measurement_metric", "first"), control=("control_definition", "first"),
        limitation=("limitation", "first"), assumption=("effect_assumption", "first"),
        refs=("evidence_refs", lambda s: ";".join(s.dropna())), status=("benefit_status", "first")).reset_index()

    fig = figure(height=170, barmode="stack")
    for i, r in enumerate(by.itertuples()):
        fig.add_trace(go.Bar(y=["Budget"], x=[r.cost], name=r.name, orientation="h",
                             marker=dict(color=SERIES[i % 8], line=dict(color=SURFACE, width=2)),
                             hovertemplate=f"{html.escape(r.name)}: %{{x:$,.0f}}<extra></extra>"))
    fig.add_trace(go.Bar(y=["Budget"], x=[max(kept, 0)], name="Kept", orientation="h",
                         marker=dict(color=BAND, line=dict(color=SURFACE, width=2)),
                         hovertemplate="Kept: %{x:$,.0f}<extra></extra>"))
    fig.update_layout(xaxis=dict(range=[0, max(BUDGET, spent)], tickprefix="$", tickformat="~s", showgrid=True,
                                 gridcolor=GRID),
                      yaxis=dict(visible=False), margin=dict(t=36, b=4, l=4, r=12), legend_traceorder="normal")
    budget = Chart("plan-budget", "Where the $100,000 goes", fig, "mart_actions", wide=True)

    with_benefit = by.dropna(subset=["net"])
    fig2 = figure(height=80 + 70 * max(len(with_benefit), 1))
    fig2.add_vline(x=0, line_color=AXIS, line_width=1)
    fig2.add_trace(go.Scatter(x=with_benefit.net, y=with_benefit.name, mode="markers", name="Expected net benefit",
                              marker=dict(color=BLUE, size=12, line=dict(color=SURFACE, width=2)),
                              error_x=dict(type="data", symmetric=False, array=with_benefit.high - with_benefit.net,
                                           arrayminus=with_benefit.net - with_benefit.low, color=BLUE, thickness=2,
                                           width=6),
                              customdata=with_benefit[["cost", "low", "high"]],
                              hovertemplate="<b>%{y}</b><br>Net %{x:$,.0f} after a %{customdata[0]:$,.0f} cost"
                                            "<br>Range %{customdata[1]:$,.0f} to %{customdata[2]:$,.0f}<extra></extra>"))
    fig2.add_trace(go.Scatter(x=with_benefit.half, y=with_benefit.name, mode="markers", name="At half the effect",
                              marker=dict(color=ORANGE, size=11, symbol="diamond", line=dict(color=SURFACE, width=2)),
                              hovertemplate="<b>%{y}</b> at half the effect: %{x:$,.0f}<extra></extra>"))
    money_axis(fig2, "xaxis", "Net benefit over July, after cost")
    fig2.update_layout(xaxis=dict(showgrid=True, gridcolor=GRID), yaxis=dict(showgrid=False, autorange="reversed"))
    payoff = Chart("plan-payoff", "What each action should return", fig2, "mart_actions", wide=True,
                   subtitle="Dots are the estimate, bars the low-to-high scenarios, diamonds the plan with "
                            "half the assumed effect. Information-only actions, like inspections, have no "
                            "dollar estimate and aren't shown.")

    rows = []
    for r in by.itertuples():
        rows.append({
            "Action": r.full_name, "Targets": f"{r.target_type}: {r.targets}", "Units": int(r.qty),
            "Cost": fmt_money(r.cost), "Live days in July": fmt_num(r.days),
            "Net benefit": fmt_money(r.net) if pd.notna(r.net) else "Information only",
            "Range": f"{fmt_money(r.low)} to {fmt_money(r.high)}" if pd.notna(r.low) else "–",
            "At half effect": fmt_money(r.half) if pd.notna(r.half) else "–",
            "Assumption": r.assumption, "How we'll measure it": r.metric, "Compared against": r.control,
            "Limitation": r.limitation, "Evidence": _evidence_links(r.refs, f)})
    plan_html = _cards(rows)

    cat = action_catalog()
    limits = dict(zip(cat.action_type_id, cat.quantity_limit)) if not cat.empty else {}
    groups = dict(zip(cat.action_type_id, cat.incompatibility_group)) if not cat.empty else {}
    over = [f"{r.name} ({int(r.qty)} of {int(limits[r.action_type_id])})" for r in by.itertuples()
            if r.action_type_id in limits and r.qty > limits[r.action_type_id]]
    same = a[a.action_type_id.map(groups).eq("same_machine")]
    clashes = same.groupby("target_id").action_type_id.nunique()
    clashes = list(clashes[clashes > 1].index)
    comp_both = {"A-COMP-PILOT", "A-COMP-CHANGE"} <= set(a.action_type_id)
    horizon_ok = (pd.Timestamp(a.horizon_start.min()) >= pd.Timestamp("2025-07-01")
                  and pd.Timestamp(a.horizon_end.max()) <= pd.Timestamp("2025-07-30")) if len(a) else True
    checks = [
        (spent <= BUDGET, f"Spends {fmt_money(spent)} of {fmt_money(BUDGET)}"),
        (by.action_type_id.nunique() <= MAX_ACTION_TYPES,
         f"{plural(by.action_type_id.nunique(), 'action type')}, limit {MAX_ACTION_TYPES}"),
        (not over, "Within catalogue quantity limits" if not over else "Over the limit: " + ", ".join(over)),
        (not clashes, "No machine is both moved and replaced" if not clashes
         else "Conflicting actions on " + ", ".join(clashes)),
        (not comp_both, "Comp pilot and floor-wide comp change aren't combined"),
        (horizon_ok, "Every action runs inside July 1–30"),
    ]
    check_html = Markup('<ul class="checks">' + "".join(
        f'<li class="{"ok" if ok else "fail"}"><span aria-hidden="true">{"✓" if ok else "✕"}</span>'
        f'<span class="sr">{"Passes" if ok else "Fails"}: </span>{html.escape(txt)}</li>'
        for ok, txt in checks) + "</ul>")

    lines = a[["proposal_line_id", "name", "target_type", "target_id", "quantity", "lead_days",
               "effective_operating_days", "action_downtime_hours", "total_cost_usd", "net_benefit_usd",
               "benefit_status"]]
    lines.columns = ["Line", "Action", "Target type", "Target", "Qty", "Lead days", "Live days", "Downtime (h)",
                     "Cost", "Net benefit", "Status"]
    net, half = a.net_benefit_usd.sum(min_count=1), a.half_effect_net_benefit_usd.sum(min_count=1)
    return {
        "headline": plan_story(a),
        "lede": "Each action answers a cause found in an earlier chapter, and its evidence links back there. "
                "Costs follow the catalogue: unit cost plus daily cost for the July days left after lead time.",
        "rail": [
            tile("Spent", fmt_money(spent), f"of {fmt_money(BUDGET)}", "pos" if spent <= BUDGET else "neg"),
            tile("Kept", fmt_money(kept), "Keeping money is a valid choice"),
            tile("Action types", f"{by.action_type_id.nunique()} of {MAX_ACTION_TYPES}", "Most we may fund"),
            tile("Expected net benefit", fmt_money(net) if pd.notna(net) else "–",
                 f"{fmt_money(a.benefit_low_usd.sum(min_count=1))} to {fmt_money(a.benefit_high_usd.sum(min_count=1))}"),
            tile("At half the effect", fmt_money(half) if pd.notna(half) else "–", "Sensitivity",
                 "pos" if pd.notna(half) and half >= 0 else "neg"),
        ],
        "sections": [
            {"charts": [budget, payoff]},
            {"title": "The actions", "blocks": [plan_html], "source": "mart_actions, names from action_catalog"},
            {"title": "Plan checks", "blocks": [check_html], "source": "mart_actions, action_catalog"},
            {"title": "Every proposal line", "source": "mart_actions",
             "blocks": [table(lines, {"Cost": fmt_money, "Net benefit": fmt_money, "Live days": fmt_num,
                                      "Downtime (h)": lambda v: fmt_num(v, 1)},
                              {"Target": lambda r: machine_link(f)(r.Target) if r["Target type"] == "machine" else ""})]},
        ],
        "meaning": "We judge each action on July theo against the forecast and a control group, not on "
                   "house win: thirty days of house win is too noisy to tell an action from luck.",
        "no_filters": True,
    }


def _cards(rows: list[dict]) -> Markup:
    """One card per action type: the decision on top, the accountability details beneath."""
    out = ['<div class="action-cards">']
    for r in rows:
        dl = "".join(f"<dt>{html.escape(k)}</dt><dd>{v if isinstance(v, Markup) else html.escape(str(v))}</dd>"
                     for k, v in r.items() if k not in ("Action", "Cost", "Net benefit"))
        out.append(f'<article class="action-card"><header><h3>{html.escape(r["Action"])}</h3>'
                   f'<p class="action-money"><span>{r["Cost"]}</span> cost, <span>{r["Net benefit"]}</span> net</p>'
                   f'</header><dl>{dl}</dl></article>')
    out.append("</div>")
    return Markup("".join(out))


# =========================================================================================
# The case (opening page)
# =========================================================================================
def case() -> dict:
    f = Filters()
    sc = scorecard(f)
    naive = sc[sc.naive_bottom_10].sort_values("naive_rank")
    spots = []
    for i, name in enumerate(SPOTS):
        chips = naive[naive.spot == name]
        # Spots sit on an arc like the betting circles on a blackjack table (SVG viewBox 1000 x 480).
        theta = np.radians(152 - i * (124 / (len(SPOTS) - 1)))
        spots.append({"name": name, "note": SPOT_NOTES[name], "machine": name in MACHINE_SPOTS,
                      "x": round((500 + 380 * np.cos(theta)) / 10, 2),
                      "y": round((40 + 300 * np.sin(theta)) / 4.8, 2),
                      "chips": [{"id": r.machine_id, "label": r.label, "href": f"/machines/{r.machine_id}"}
                                for r in chips.itertuples()]})
    head, meaning, _ = verdict_story(sc)
    stories = {
        "verdict": head, "machines": machines_story(f), "demand": demand_story(f),
        "downtime": downtime_story(f), "guests": guests_story(f), "forecast": forecast_story(),
        "plan": plan_story(),
    }
    chapters = [{"num": i + 1, "endpoint": ep, "title": title, "tag": tag, "question": q, "story": stories[ep]}
                for i, (ep, title, tag, q) in enumerate(CHAPTERS)]
    return {"spots": spots, "headline": head, "meaning": meaning, "chapters": chapters,
            "machine_count": int(sc.machine_id.nunique())}
