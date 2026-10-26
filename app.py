"""
Streamlit UI for the judge range analysis.

Run locally:   streamlit run app.py
Password:      set APP_PASSWORD in .streamlit/secrets.toml (or in the host's secrets settings).
"""

import hashlib
import hmac
import math
import pickle
from datetime import datetime
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import analysis

# ---------- Version compatibility (older Streamlit, e.g. Anaconda's, and newer alike) ----------
_ST_VER = tuple(int(x) for x in st.__version__.split(".")[:2])
STRETCH = {"width": "stretch"} if _ST_VER >= (1, 50) else {"use_container_width": True}
CONTENT = {"width": "content"} if _ST_VER >= (1, 50) else {"use_container_width": False}


def columns(spec, align="bottom"):
    try:
        return st.columns(spec, vertical_alignment=align)
    except TypeError:  # very old Streamlit
        return st.columns(spec)


# ---------- Look and feel ----------
ICE, ICE_LIGHT, NEAR, OUT = "#2E6FD8", "#9EC3F5", "#E8A33D", "#D9534F"
INK, MUTED = "#1B2333", "#5B6577"
COMPONENTS = ["Composition", "Presentation", "Skating Skills"]
GOE_STATUS = {"In range": ICE, "Within ±1": NEAR, "Outside ±1": OUT}
COMP_STATUS = {"In range": ICE, "Within ±0.25": NEAR, "Outside ±0.25": OUT}

st.set_page_config(page_title="Judge Range Analysis", page_icon="⛸️", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(
    f"""
    <style>
      .block-container {{padding-top: 2rem; max-width: 1200px;}}
      h1 {{font-weight: 700; letter-spacing: -0.02em;}}
      .subtle {{opacity: 0.7; font-size: 0.95rem; margin-top: -0.6rem;}}
      [data-testid="InputInstructions"] {{display: none;}}

      .result-head .comp {{font-size: 0.8rem; font-weight: 600; letter-spacing: 0.06em;
                           text-transform: uppercase; color: {ICE}; margin-bottom: 0.15rem;}}
      .result-head .who {{font-size: 1.75rem; font-weight: 700; color: {INK}; line-height: 1.2;}}
      .result-head .meta {{color: {MUTED}; font-size: 0.95rem; margin-top: 0.2rem;}}

      .stats {{display: grid; grid-template-columns: 1fr 1fr; gap: 0 56px;
               padding: 18px 0 20px; margin: 4px 0 14px;
               border-top: 1px solid #E6EAF0; border-bottom: 1px solid #E6EAF0;}}
      @media (max-width: 640px) {{ .stats {{grid-template-columns: 1fr; gap: 18px;}} }}
      .stat .label {{font-size: 0.78rem; font-weight: 600; letter-spacing: 0.07em;
                     text-transform: uppercase; color: {MUTED};}}
      .stat .value {{font-size: 1.9rem; font-weight: 650; color: {INK}; line-height: 1.2;
                     margin-top: 2px; font-variant-numeric: tabular-nums;}}
      .stat .value small {{font-size: 0.9rem; font-weight: 500; color: {MUTED}; margin-left: 0.35rem;}}
      .stat .sub {{font-size: 0.88rem; color: {MUTED}; margin-top: 4px;}}
      .stat .sub b {{color: {INK}; font-weight: 600;}}

      [data-testid="stButtonGroup"] button {{min-height: 2.6rem; padding: 0 1.4rem; font-size: 1rem;}}
      .legend {{font-size: 0.85rem; color: {MUTED}; margin-bottom: 1.25rem;}}
      .legend .item {{display: inline-flex; align-items: center; margin-right: 16px;}}
      .legend .swatch {{width: 11px; height: 11px; margin-right: 6px;}}
    </style>
    """,
    unsafe_allow_html=True,
)


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def legend(items):
    """items: (text, color, round?) tuples."""
    html('<div class="legend">' + "".join(
        f'<span class="item"><span class="swatch" style="background:{c};'
        f'border-radius:{"50%" if dot else "2px"}"></span>{t}</span>'
        for t, c, dot in items
    ) + "</div>")


def pct(num, den):
    return round(float(num) / float(den) * 100, 1) if den else None


def fmt_pct(value):
    return "–" if value is None else f"{value:.1f}%"


# ---------- Private access ----------
def get_password():
    # Older Streamlit shows an error box if secrets are read with no secrets file,
    # so only look when one exists.
    secret_files = [Path.home() / ".streamlit" / "secrets.toml",
                    Path(__file__).parent / ".streamlit" / "secrets.toml"]
    if _ST_VER < (1, 50) and not any(p.exists() for p in secret_files):
        return None
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:  # no secrets file at all
        return None


def check_password():
    """Simple shared-password gate. Skipped if no APP_PASSWORD is configured."""
    expected = get_password()
    if not expected or st.session_state.get("authed"):
        return True

    st.title("⛸️ Judge Range Analysis")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Enter"):
            if hmac.compare_digest(pw, expected):
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()


# ---------- Fetching ----------
@st.cache_data(ttl=3600, show_spinner=False)
def cached_competition(comp_url):
    return analysis.get_competition(comp_url)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_process_event(event_url, judge_name, base_url):
    stats = analysis.process_event(event_url, judge_name, base_url)
    skipped = stats.attrs.get("skipped", 0) if stats is not None else 0
    return stats, skipped


def url_tail(url):
    parts = [p for p in url.split("/") if p and p != "index.asp"]
    return "/".join(parts[-2:]) if len(parts) >= 2 else url


def run_analysis(comp_url, judge_name):
    """Fetch every event and return a run: one dict holding everything the page shows."""
    comp, base_url, event_links = cached_competition(comp_url)
    run = {"url": comp_url, "name": judge_name, "comp": comp or url_tail(comp_url),
           "results": [], "n_events": len(event_links), "skipped": 0, "failed": 0,
           "saved": datetime.now()}
    bar = st.progress(0.0, text="Checking events…")
    for i, url in enumerate(event_links, start=1):
        bar.progress(i / len(event_links), text=f"Checking event {i} of {len(event_links)}")
        try:
            stats, skipped = cached_process_event(url, judge_name, base_url)
        except Exception:
            run["failed"] += 1
            continue
        if stats is not None:
            run["results"].append(stats)
            run["skipped"] += skipped
    bar.empty()
    return run


# ---------- Saved runs (kept on disk between sessions) ----------
SAVE_DIR = Path(__file__).parent / "saved_runs"


def _run_path(comp_url, judge_name):
    key = f"{comp_url.strip().lower()}|{judge_name.strip().lower()}"
    return SAVE_DIR / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".pkl")


def _normalize(record):
    """Saved runs from earlier versions stored a tuple under "out"; upgrade them to a run dict."""
    if "out" in record:
        results, n_events, skipped, failed = record["out"]
        record = {"url": record["url"], "name": record["name"], "comp": url_tail(record["url"]),
                  "results": results, "n_events": n_events, "skipped": skipped,
                  "failed": failed, "saved": record["saved"]}
    return record


def save_run(run):
    SAVE_DIR.mkdir(exist_ok=True)
    with open(_run_path(run["url"], run["name"]), "wb") as f:
        pickle.dump(run, f)


def load_run(comp_url, judge_name):
    try:
        with open(_run_path(comp_url, judge_name), "rb") as f:
            return _normalize(pickle.load(f))
    except Exception:
        return None


def list_runs():
    runs = []
    for path in SAVE_DIR.glob("*.pkl") if SAVE_DIR.exists() else []:
        try:
            with open(path, "rb") as f:
                runs.append(_normalize(pickle.load(f)))
        except Exception:
            continue
    return sorted(runs, key=lambda r: r["saved"], reverse=True)


def run_label(run):
    return (f'{run["name"]} · {run["comp"]} · {len(run["results"])} events · '
            f'saved {run["saved"]:%b %d, %I:%M %p}')


# ---------- Inputs ----------
def show_run(run):
    st.session_state["run"] = run


def input_panel():
    """Saved-run picker plus the URL/name form. Re-runs the page once a run is loaded."""
    saved = {run_label(r): r for r in list_runs()}
    if saved:
        def open_saved():
            show_run(saved[st.session_state["saved_pick"]])
            st.session_state["saved_pick"] = None

        st.selectbox("Open a saved run", list(saved), index=None, key="saved_pick",
                     placeholder="Pick a saved run to open it instantly…", on_change=open_saved)

    with st.form("inputs"):
        c_url, c_name, c_btn = columns([3, 1.4, 1])
        comp_url = c_url.text_input(
            "Competition results URL",
            placeholder="https://ijs.usfigureskating.org/leaderboard/results/2025/36167/index.asp",
        )
        judge_name = c_name.text_input("Official's full name", placeholder="Full Name")
        submitted = c_btn.form_submit_button("Run analysis", type="primary", **STRETCH)
        refresh = st.checkbox("Re-fetch from the results site even if this run is saved")

    if not submitted:
        return
    url, name = comp_url.strip(), judge_name.strip()
    if not url or not name:
        st.error("Enter both a URL and a name.")
        return

    run = None if refresh else load_run(url, name)
    if run is None:
        try:
            if refresh:
                st.cache_data.clear()
            run = run_analysis(url, name)
        except Exception as e:
            st.error(f"Couldn't read that competition page: {e}")
            return
        if run["results"]:
            save_run(run)
    show_run(run)
    st.rerun()  # redraw with the input area folded away


# ---------- Reshaping for display ----------
def event_summary(results):
    rows = []
    for df in results:
        t = df.iloc[-1]
        rows.append({
            "Event": df.iloc[0]["Skater"],
            "Skaters": len(df) - 2,
            "GOEs": int(t["# of GOEs"]),
            "goe_exact": pct(t["# of GOEs w/in Range"], t["# of GOEs"]),
            "goe_tol": pct(t["# of GOEs w/in Range +/- 1"], t["# of GOEs"]),
            "Components": int(t["# of Components"]),
            "comp_exact": pct(t["# Components w/in Range"], t["# of Components"]),
            "comp_tol": pct(t["# of Components w/in Range +/- .25"], t["# of Components"]),
        })
    return pd.DataFrame(rows)


def comp_status(lo, hi, mark):
    if lo <= mark <= hi:
        return "In range"
    return "Within ±0.25" if lo - 0.25 <= mark <= hi + 0.25 else "Outside ±0.25"


def goe_status(lo, hi, mark):
    if lo <= mark <= hi:
        return "In range"
    return "Within ±1" if lo - 1 <= mark <= hi + 1 else "Outside ±1"


def component_points(df):
    """One row per skater x component: rest-of-panel min/max and my mark."""
    rows = []
    for _, r in df.iloc[1:-1].iterrows():
        for comp in COMPONENTS:
            lo, hi = (float(x) for x in str(r[comp]).split(" - "))
            mine = float(r[f"My {comp}"])
            rows.append({"Skater": r["Skater"], "Component": comp, "Panel min": lo,
                         "Panel max": hi, "Mine": mine, "Status": comp_status(lo, hi, mine)})
    return pd.DataFrame(rows)


def element_points(df):
    raw = df.attrs.get("elements")
    el = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw or [])
    if el.empty:
        return el
    el["Status"] = [goe_status(*v) for v in zip(el["Panel min"], el["Panel max"], el["My GOE"])]
    el["Label"] = el["#"].astype(int).astype(str) + ". " + el["Element"].astype(str)
    return el


# ---------- Results: header and cards ----------
def results_header(run, results):
    left, right = columns([4, 1], align="center")
    with left:
        html(f'<div class="result-head"><div class="comp">{escape(run["comp"])}</div>'
             f'<div class="who">{escape(run["name"])}</div>'
             f'<div class="meta">Judged {len(results)} of {run["n_events"]} events</div></div>')
    csv = analysis.combine_results(results).to_csv(index=False).encode("utf-8")
    right.download_button("Download CSV", csv, mime="text/csv", **STRETCH,
                          file_name=f"judge_range_{run['name'].replace(' ', '_')}.csv")

    problems = []
    if run["skipped"]:
        problems.append(f"{run['skipped']} skater score sheet{'s' if run['skipped'] != 1 else ''}")
    if run["failed"]:
        problems.append(f"{run['failed']} event page{'s' if run['failed'] != 1 else ''}")
    if problems:
        single = len(problems) == 1 and run["skipped"] + run["failed"] == 1
        st.warning(f"{' and '.join(problems)} couldn't be read and "
                   f"{'isn’t' if single else 'aren’t'} included in the totals.")


def stat(label, exact, tolerance, tol_text, count_text):
    """Big in-range %, with the tolerance % and count on a detail line underneath."""
    return (f'<div class="stat"><div class="label">{label}</div>'
            f'<div class="value">{fmt_pct(exact)}<small>in panel range</small></div>'
            f'<div class="sub"><b>{fmt_pct(tolerance)}</b> {tol_text} · {count_text}</div></div>')


def headline_stats(results):
    totals = pd.concat([df.iloc[-1:] for df in results])
    goes, comps = totals["# of GOEs"].sum(), totals["# of Components"].sum()
    html('<div class="stats">'
         + stat("GOEs", pct(totals["# of GOEs w/in Range"].sum(), goes),
                pct(totals["# of GOEs w/in Range +/- 1"].sum(), goes),
                "within ±1", f"{int(goes)} GOEs")
         + stat("Components", pct(totals["# Components w/in Range"].sum(), comps),
                pct(totals["# of Components w/in Range +/- .25"].sum(), comps),
                "within ±0.25", f"{int(comps)} marks")
         + "</div>")


# ---------- Overview ----------
def overview_bars(summary, exact, tol, title, show_labels):
    """One bar per event: exact-range % in dark blue, the tolerance extension in light blue."""
    base = alt.Chart(summary, title=alt.TitleParams(title, anchor="start", fontSize=14)).encode(
        y=alt.Y("Event:N", sort=None, title=None,
                axis=alt.Axis(labels=show_labels, ticks=False, domain=False, labelLimit=240,
                              labelFontSize=13, labelColor=INK, labelPadding=10)),
        tooltip=["Event", alt.Tooltip(f"{exact}:Q", title="In range %", format=".1f"),
                 alt.Tooltip(f"{tol}:Q", title="With tolerance %", format=".1f")],
    )
    x = alt.X(f"{tol}:Q", scale=alt.Scale(domain=[0, 100]), title=None,
              axis=alt.Axis(values=list(range(0, 101, 20)), labelExpr="datum.value + '%'"))
    tolerance = base.mark_bar(color=ICE_LIGHT, size=18, cornerRadiusEnd=3).encode(x=x)
    in_range = base.mark_bar(color=ICE, size=18).encode(x=f"{exact}:Q")
    return (tolerance + in_range).properties(height=alt.Step(36))


def overview(results):
    summary = event_summary(results)
    legend([("In panel range", ICE, False),
            ("Extra with tolerance (GOE ±1, components ±0.25)", ICE_LIGHT, False)])
    left, right = st.columns([1.4, 1])
    left.altair_chart(overview_bars(summary, "goe_exact", "goe_tol", "GOEs", True), **STRETCH)
    right.altair_chart(overview_bars(summary, "comp_exact", "comp_tol", "Components", False), **STRETCH)

    progress = lambda label: st.column_config.ProgressColumn(  # noqa: E731
        label, format="%.1f%%", min_value=0, max_value=100)
    st.dataframe(summary, hide_index=True, **STRETCH, column_config={
        "goe_exact": progress("GOE in range"), "goe_tol": progress("GOE ±1"),
        "comp_exact": progress("Comp. in range"), "comp_tol": progress("Comp. ±0.25"),
    })


# ---------- By event ----------
def range_dot_layers(y, x_scale, x_axis, mark_field, status_scale, tooltip):
    """
    Shared look: light bar = rest of panel's range, dot = my mark coloured by status.
    When the whole panel agreed (min == max) the bar has no length, so a small light dot marks it.
    """
    x = lambda field: alt.X(f"{field}:Q", scale=x_scale, axis=x_axis, title=None)  # noqa: E731
    bar = alt.Chart().mark_rule(strokeWidth=7, opacity=0.35, color=ICE, strokeCap="round").encode(
        y=y, x=x("Panel min"), x2="Panel max:Q")
    agreed = (alt.Chart().mark_point(filled=True, size=55, opacity=1, color=ICE_LIGHT)
              .encode(y=y, x=x("Panel min"))
              .transform_filter("datum['Panel min'] == datum['Panel max']"))
    dot = alt.Chart().mark_point(filled=True, size=85, opacity=1).encode(
        y=y, x=x(mark_field), tooltip=tooltip,
        color=alt.Color("Status:N", scale=status_scale, legend=None))
    return [bar, agreed, dot]


def component_chart(pts):
    lo = math.floor((min(pts["Panel min"].min(), pts["Mine"].min()) - 0.25) * 2) / 2
    hi = math.ceil((max(pts["Panel max"].max(), pts["Mine"].max()) + 0.25) * 2) / 2
    y = alt.Y("Skater:N", sort=None, title=None,
              axis=alt.Axis(labelAlign="left", labelPadding=150, labelLimit=144, ticks=False,
                            labelFontSize=12, labelColor=INK))
    layers = range_dot_layers(
        y, alt.Scale(domain=[lo, hi]), alt.Axis(), "Mine",
        alt.Scale(domain=list(COMP_STATUS), range=list(COMP_STATUS.values())),
        ["Skater", "Component", alt.Tooltip("Mine:Q", title="My mark"), "Panel min", "Panel max", "Status"])
    # One faceted chart: fixed-width name column and equal panels, identical in every event.
    return (alt.layer(*layers, data=pts)
            .properties(width=250, height=alt.Step(34))
            .facet(column=alt.Column("Component:N", sort=COMPONENTS, title=None,
                                     header=alt.Header(labelFontSize=14, labelFontWeight="bold",
                                                       labelColor=INK, labelAnchor="start")),
                   spacing=28))


def goe_grid(el, titles):
    """
    All skaters' element charts as ONE faceted chart (one panel per skater, two per row).
    A single chart renders far faster than one chart per skater. Each panel is padded with
    blank rows to the longest program so every panel is the same height.
    """
    rows = int(el.groupby("Skater").size().max())
    parts = []
    for skater, title in titles.items():
        sub = el[el["Skater"] == skater].assign(Title=title, First=False)
        sub.iloc[0, sub.columns.get_loc("First")] = True  # draw the zero line once per panel
        filler = pd.DataFrame({"Skater": skater, "Title": title, "First": False,
                               "Label": [" " * (k + 1) for k in range(rows - len(sub))]})
        parts += [sub, filler]
    data = pd.concat(parts, ignore_index=True)

    y = alt.Y("Label:N", sort=None, title=None,
              axis=alt.Axis(labelAlign="left", labelPadding=130, labelLimit=124, ticks=False,
                            labelColor=INK))
    x_scale = alt.Scale(domain=[-5.5, 5.5])
    x_axis = alt.Axis(values=list(range(-5, 6)), labelOverlap=False, grid=True)
    layers = range_dot_layers(
        y, x_scale, x_axis, "My GOE",
        alt.Scale(domain=list(GOE_STATUS), range=list(GOE_STATUS.values())),
        ["Element", "My GOE", "Panel min", "Panel max", "Status"])
    zero = (alt.Chart().mark_rule(color="#AEB5C2", strokeWidth=1)  # light, so a panel range sitting at 0 stays visible
            .encode(x=alt.X(datum=0, scale=x_scale, axis=x_axis, title=None))
            .transform_filter("datum.First"))
    return (alt.layer(zero, *layers, data=data)
            .properties(width=290, height=alt.Step(24))
            .facet(facet=alt.Facet("Title:N", sort=list(titles.values()), title=None,
                                   header=alt.Header(labelAnchor="start", labelFontSize=13,
                                                     labelFontWeight="bold", labelColor=INK,
                                                     labelLimit=420)),
                   columns=2, spacing={"row": 24, "column": 48})
            .resolve_scale(y="independent")
            .resolve_axis(x="independent"))  # GOE numbers under every panel, not just the last row


def skater_table(df, pts):
    """Compact per-skater table; component cells show my mark (panel range), coloured by status."""
    marks = {(p["Skater"], p["Component"]): p for p in pts.to_dict("records")}
    rows, colors = [], []
    for _, r in df.iloc[1:-1].iterrows():
        row = {"Skater": r["Skater"], "GOEs": int(r["# of GOEs"]),
               "GOE in range": pct(r["# of GOEs w/in Range"], r["# of GOEs"]),
               "GOE ±1": pct(r["# of GOEs w/in Range +/- 1"], r["# of GOEs"])}
        shade = {}
        for comp in COMPONENTS:
            p = marks[(r["Skater"], comp)]
            row[comp] = f'{p["Mine"]:.2f}  ({p["Panel min"]:.2f}–{p["Panel max"]:.2f})'
            shade[comp] = f'color: {COMP_STATUS[p["Status"]]}; font-weight: 600'
        row["Comp. in range"] = pct(r["# Components w/in Range"], 3)
        row["Comp. ±0.25"] = pct(r["# of Components w/in Range +/- .25"], 3)
        rows.append(row)
        colors.append(shade)

    t = df.iloc[-1]
    rows.append({"Skater": "Event total", "GOEs": int(t["# of GOEs"]), **{c: "" for c in COMPONENTS},
                 "GOE in range": pct(t["# of GOEs w/in Range"], t["# of GOEs"]),
                 "GOE ±1": pct(t["# of GOEs w/in Range +/- 1"], t["# of GOEs"]),
                 "Comp. in range": pct(t["# Components w/in Range"], t["# of Components"]),
                 "Comp. ±0.25": pct(t["# of Components w/in Range +/- .25"], t["# of Components"])})
    colors.append({})

    table = pd.DataFrame(rows)
    styles = pd.DataFrame([{c: s.get(c, "") for c in table.columns} for s in colors])
    styles.iloc[-1] = "font-weight: 600"
    pct_cols = ["GOE in range", "GOE ±1", "Comp. in range", "Comp. ±0.25"]
    return (table.style.apply(lambda _: styles, axis=None)
            .format({c: "{:.1f}%" for c in pct_cols}, na_rep=""))


def by_event(df):
    pts = component_points(df)
    html("<b>Components</b>: my mark (dot) vs. rest of panel (bar)")
    legend([("In range", ICE, True), ("Within ±0.25", NEAR, True),
            ("Outside ±0.25", OUT, True), ("Rest of panel", ICE_LIGHT, False)])
    st.altair_chart(component_chart(pts), **CONTENT)

    html("<b>GOEs</b>: my mark (dot) vs. rest of panel (bar), per element")
    el = element_points(df)
    if el.empty:
        st.info("No element detail for this event. If this is an older saved run, tick "
                "“Re-fetch from the results site” and run it again.")
    else:
        legend([("In range", ICE, True), ("Within ±1", NEAR, True),
                ("Outside ±1", OUT, True), ("Rest of panel", ICE_LIGHT, False)])
        only_out = st.checkbox("Only show skaters with a GOE outside the panel range")
        skaters = list(dict.fromkeys(el["Skater"]))
        if only_out:
            skaters = [k for k in skaters if (el.loc[el["Skater"] == k, "Status"] != "In range").any()]
            if not skaters:
                st.success("Every GOE in this event is inside the rest of the panel's range.")
        if skaters:
            titles = {}
            for skater in skaters:
                r = df[df["Skater"] == skater].iloc[0]
                titles[skater] = (f"{skater}  ·  "
                                  f"{fmt_pct(pct(r['# of GOEs w/in Range'], r['# of GOEs']))} in range")
            st.altair_chart(goe_grid(el, titles), **CONTENT)

    html("<b>Skater detail</b>")
    st.dataframe(skater_table(df, pts), hide_index=True, **STRETCH)
    st.caption("Component cells show my mark, then the rest of the panel's range, coloured like the chart.")


# ---------- Page ----------
st.title("⛸️ Judge Range Analysis")
html('<p class="subtle">How often a judge\'s GOEs and program components fall inside '
     "the rest of the panel's range.</p>")

run = st.session_state.get("run")
if run is None:
    with st.container(border=True):
        input_panel()
    st.info("Enter a competition URL and a judge's name above, then click Run analysis. "
            "Each run is saved so it opens instantly next time.")
    st.stop()

with st.expander("Run another analysis or open a saved run"):
    input_panel()

results = run["results"]
if not results:
    st.warning(f"{run['name']} wasn't found on any of the {run['n_events']} event panels.")
    st.stop()

results_header(run, results)
headline_stats(results)

# A remembered toggle with the event picker beside it (st.tabs would jump back on every rerun).
VIEWS = ["Overview", "By event"]
nav, picker = columns([1.2, 2.8])
with nav:
    if hasattr(st, "segmented_control"):
        view = st.segmented_control("View", VIEWS, default="Overview", key="view",
                                    label_visibility="collapsed")
    else:
        view = st.radio("View", VIEWS, horizontal=True, key="view", label_visibility="collapsed")
view = view or "Overview"  # segmented_control returns None if the active option is clicked again

if view == "Overview":
    overview(results)
else:
    names = [df.iloc[0]["Skater"] for df in results]
    run_key = hashlib.sha1(f'{run["url"]}|{run["name"]}'.encode()).hexdigest()[:8]
    choice = picker.selectbox("Event", names, key=f"event_{run_key}", label_visibility="collapsed")
    by_event(results[names.index(choice)])
