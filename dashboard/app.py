"""The Gilded Ace slot floor review (Flask).

    python build_duckdb.py                # placeholder database, shaped like the mart contract
    python -m dashboard.app               # then open http://127.0.0.1:5000

Data source: see dashboard/data.py. Once the real pipeline writes output/casino.duckdb, the
dashboard uses it automatically and the placeholder banner disappears.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import plotly
from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from . import pages
from .contract import CLASSES
from .data import DB_PATH, PERIOD_END, PERIOD_START, Filters, filter_options, is_placeholder

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True   # template edits show up without a restart
PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
app.jinja_env.filters["todate"] = date.fromisoformat

BUILDERS = {"verdict": pages.verdict, "machines": pages.machines, "demand": pages.demand,
            "downtime": pages.downtime, "guests": pages.guests, "forecast": pages.forecast, "plan": pages.plan}


@app.context_processor
def inject_globals():
    return {"chapters": pages.CHAPTERS, "placeholder": is_placeholder(), "period_start": PERIOD_START,
            "period_end": PERIOD_END, "class_options": [(k, v[0]) for k, v in CLASSES.items()]}


def chapter_meta(endpoint: str) -> dict:
    i = next(i for i, (ep, *_rest) in enumerate(pages.CHAPTERS) if ep == endpoint)
    ep, title, tag, question = pages.CHAPTERS[i]
    prev = pages.CHAPTERS[i - 1] if i > 0 else None
    nxt = pages.CHAPTERS[i + 1] if i + 1 < len(pages.CHAPTERS) else None
    return {"num": i + 1, "endpoint": ep, "title": title, "tag": tag, "question": question,
            "prev": {"endpoint": prev[0], "title": prev[1], "num": i} if prev else None,
            "next": {"endpoint": nxt[0], "title": nxt[1], "num": i + 2} if nxt else None}


def render_chapter(endpoint: str, *args):
    f = Filters.from_args(request.args)
    builder = pages.machine_detail if args else BUILDERS[endpoint]
    page = builder(f, *args)
    if page is None:
        abort(404)
    return render_template("chapter.html", page=page, meta=chapter_meta(endpoint), f=f,
                           opts=filter_options(), active=endpoint)


@app.route("/")
def case():
    return render_template("case.html", case=pages.case(), f=Filters(), active="case")


@app.route("/verdict")
def verdict():
    return render_chapter("verdict")


@app.route("/machines")
def machines():
    return render_chapter("machines")


@app.route("/machines/<machine_id>")
def machine_detail(machine_id: str):
    return render_chapter("machines", machine_id)


@app.route("/demand")
def demand():
    return render_chapter("demand")


@app.route("/downtime")
def downtime():
    return render_chapter("downtime")


@app.route("/guests")
def guests():
    return render_chapter("guests")


@app.route("/forecast")
def forecast():
    return render_chapter("forecast")


@app.route("/plan")
def plan():
    return render_chapter("plan")


# Earlier URLs, kept so old links still land somewhere sensible.
@app.route("/players")
@app.route("/comps")
def old_guests():
    return redirect(url_for("guests", **request.args), 301)


@app.route("/actions")
def old_actions():
    return redirect(url_for("plan"), 301)


@app.route("/vendor/plotly.min.js")
def plotly_js():
    # Served from the installed Python package, so the JS always matches the figure JSON.
    return send_file(PLOTLY_JS, mimetype="text/javascript", max_age=86400)


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html", f=Filters(), active=""), 404


if __name__ == "__main__":
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH} not found. Run: python build_duckdb.py")
    app.run(debug=True)
