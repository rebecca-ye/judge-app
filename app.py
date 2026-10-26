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
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import analysis

# Works on older Streamlit (e.g. Anaconda's) and newer releases alike.
_ST_VER = tuple(int(x) for x in st.__version__.split(".")[:2])
STRETCH = {"width": "stretch"} if _ST_VER >= (1, 50) else {"use_container_width": True}
CONTENT = {"width": "content"} if _ST_VER >= (1, 50) else {"use_container_width": False}

st.set_page_config(page_title="Judge Range Analysis", page_icon="⛸️", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1200px;}
      h1 {font-weight: 700; letter-spacing: -0.02em;}
      [data-testid="stMetric"] {
          background: var(--secondary-background-color);
          border-radius: 12px; padding: 14px 18px;
      }
      [data-testid="stMetricLabel"] p {font-size: 0.85rem; opacity: 0.75;}
      .subtle {opacity: 0.7; font-size: 0.95rem; margin-top: -0.6rem;}
      [data-testid="InputInstructions"] {display: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

ICE = "#2E6FD8"
ICE_LIGHT = "#9EC3F5"
OUT = "#D9534F"
NEAR = "#E8A33D"


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


# ---------- Cached scraping wrappers ----------
@st.cache_data(ttl=3600, show_spinner=False)
def cached_event_links(comp_url):
    return analysis.get_event_links(comp_url)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_process_event(event_url, judge_name, base_url):
    stats = analysis.process_event(event_url, judge_name, base_url)
    skipped = stats.attrs.get("skipped", 0) if stats is not None else 0
    return stats, skipped


def run_analysis(comp_url, judge_name):
    base_url, event_links = cached_event_links(comp_url)
    results, skipped_total, failed = [], 0, 0
    bar = st.progress(0.0, text="Checking events…")
    for i, url in enumerate(event_links, start=1):
        bar.progress(i / len(event_links), text=f"Checking event {i} of {len(event_links)}")
        try:
            stats, skipped = cached_process_event(url, judge_name, base_url)
        except Exception:
            failed += 1
            continue
        if stats is not None:
            results.append(stats)
            skipped_total += skipped
    bar.empty()
    return results, len(event_links), skipped_total, failed


# ---------- Saved runs (kept on disk between sessions) ----------
SAVE_DIR = Path(__file__).parent / "saved_runs"


def _run_path(comp_url, judge_name):
    key = f"{comp_url.strip().lower()}|{judge_name.strip().lower()}"
    return SAVE_DIR / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".pkl")


def save_run(comp_url, judge_name, out):
    SAVE_DIR.mkdir(exist_ok=True)
    record = {"url": comp_url, "name": judge_name, "saved": datetime.now(), "out": out}
    with open(_run_path(comp_url, judge_name), "wb") as f:
        pickle.dump(record, f)


def load_run(comp_url, judge_name):
    path = _run_path(comp_url, judge_name)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def list_runs():
    runs = []
    for path in SAVE_DIR.glob("*.pkl") if SAVE_DIR.exists() else []:
        try:
            with open(path, "rb") as f:
                runs.append(pickle.load(f))
        except Exception:
            continue
    return sorted(runs, key=lambda r: r["saved"], reverse=True)


def run_label(r):
    parts = [p for p in r["url"].split("/") if p and p != "index.asp"]
    comp = "/".join(parts[-2:]) if len(parts) >= 2 else r["url"]
    judged = len(r["out"][0])
    return f'{r["name"]} · {comp} · {judged} events · saved {r["saved"]:%b %d, %I:%M %p}'


# ---------- Reshaping for display ----------
def pct(num, den):
    return round(num / den * 100, 1) if den else None


def event_summary(results):
    rows = []
    for df in results:
        totals = df.iloc[-1]
        rows.append({
            "Event": df.iloc[0]["Skater"],
            "Skaters": len(df) - 2,
            "GOEs": int(totals["# of GOEs"]),
            "GOE % in range": pct(totals["# of GOEs w/in Range"], totals["# of GOEs"]),
            "GOE % ±1": pct(totals["# of GOEs w/in Range +/- 1"], totals["# of GOEs"]),
            "Components": int(totals["# of Components"]),
            "Comp % in range": pct(totals["# Components w/in Range"], totals["# of Components"]),
            "Comp % ±0.25": pct(totals["# of Components w/in Range +/- .25"], totals["# of Components"]),
        })
    return pd.DataFrame(rows)


def component_points(df):
    """One row per skater x component: panel min/max (excluding judge) and judge's mark."""
    rows = []
    for _, r in df.iloc[1:-1].iterrows():
        for comp in ["Composition", "Presentation", "Skating Skills"]:
            lo, hi = (float(x) for x in str(r[comp]).split(" - "))
            tj = float(r[f"My {comp}"])
            rows.append({
                "Skater": r["Skater"], "Component": comp, "Panel min": lo, "Panel max": hi,
                "Judge": tj,
                "Status": "In range" if lo <= tj <= hi
                else ("Within ±0.25" if lo - 0.25 <= tj <= hi + 0.25 else "Outside ±0.25"),
            })
    return pd.DataFrame(rows)


# ---------- Page ----------
st.title("⛸️ Judge Range Analysis")
st.markdown(
    '<p class="subtle">How often a judge\'s GOEs and program components fall inside the rest of the panel\'s range.</p>',
    unsafe_allow_html=True,
)

saved_runs = list_runs()


labels = {run_label(r): r for r in saved_runs}


def _open_saved():
    r = labels.get(st.session_state.get("saved_pick"))
    if r is not None:
        st.session_state["result"] = (r["name"], *r["out"])


if saved_runs:
    st.selectbox(
        "Previously run", list(labels), index=None, key="saved_pick",
        placeholder="Pick a saved run to open it instantly…", on_change=_open_saved,
    )

with st.form("inputs"):
    try:
        c_url, c_name, c_btn = st.columns([3, 1.4, 1], vertical_alignment="bottom")
    except TypeError:  # very old Streamlit
        c_url, c_name, c_btn = st.columns([3, 1.4, 1])
    comp_url = c_url.text_input(
        "Competition results URL",
        placeholder="https://ijs.usfigureskating.org/leaderboard/results/2025/36167/index.asp",
    )
    judge_name = c_name.text_input("Official's full name", placeholder="Full Name")
    submitted = c_btn.form_submit_button("Run analysis", type="primary", **STRETCH)
    refresh = st.checkbox("Re-fetch from the results site even if this run is saved")

if submitted:
    url, nm = comp_url.strip(), judge_name.strip()
    if not url or not nm:
        st.error("Enter both a URL and a name.")
    else:
        saved = None if refresh else load_run(url, nm)
        if saved:
            st.session_state["result"] = (nm, *saved["out"])
            st.toast(f'Loaded saved run from {saved["saved"]:%b %d, %I:%M %p}')
        else:
            try:
                if refresh:
                    st.cache_data.clear()
                out = run_analysis(url, nm)
                st.session_state["result"] = (nm, *out)
                if out[0]:
                    save_run(url, nm, out)
            except Exception as e:
                st.error(f"Couldn't read that competition page: {e}")

if "result" not in st.session_state:
    st.info("Enter a competition URL and a judge's name above, then click Run analysis. Each run is saved so it opens instantly next time.")
    st.stop()

name, results, n_events, skipped, failed = st.session_state["result"]

if not results:
    st.warning(f"{name} wasn't found on any of the {n_events} event panels.")
    st.stop()

if skipped or failed:
    st.warning(
        f"Heads up: {skipped} skater score sheet(s) and {failed} event page(s) couldn't be parsed "
        "and are not included in the totals."
    )

summary = event_summary(results)
all_rows = pd.concat([df.iloc[-1:] for df in results])
g_tot = all_rows["# of GOEs"].sum()
c_tot = all_rows["# of Components"].sum()

st.subheader(name)
m = st.columns(5)
m[0].metric("Events judged", f"{len(results)} / {n_events}")
m[1].metric("GOE in range", f"{pct(all_rows['# of GOEs w/in Range'].sum(), g_tot)}%")
m[2].metric("GOE within ±1", f"{pct(all_rows['# of GOEs w/in Range +/- 1'].sum(), g_tot)}%")
m[3].metric("Components in range", f"{pct(all_rows['# Components w/in Range'].sum(), c_tot)}%")
m[4].metric("Comp. within ±0.25", f"{pct(all_rows['# of Components w/in Range +/- .25'].sum(), c_tot)}%")

# A remembered toggle instead of st.tabs: tabs jump back to the first tab on every rerun.
VIEWS = ["Overview", "By event"]
if hasattr(st, "segmented_control"):
    view = st.segmented_control("View", VIEWS, default="Overview", key="view",
                                label_visibility="collapsed")
else:
    view = st.radio("View", VIEWS, horizontal=True, key="view", label_visibility="collapsed")
view = view or "Overview"  # segmented_control returns None if the active option is clicked again


def range_bars(kind, exact, tol, show_labels):
    """Grouped bars per event: exact-range % and with-tolerance %."""
    data = summary.melt(id_vars="Event", value_vars=[exact, tol], var_name="Measure", value_name="Percent")
    data["Band"] = data["Measure"].map({exact: "Exact range", tol: "With tolerance"})
    return (
        alt.Chart(data, title=kind)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("Event:N", sort=None, title=None,
                    axis=alt.Axis(labelLimit=220, labels=show_labels, ticks=show_labels)),
            x=alt.X("Percent:Q", scale=alt.Scale(domain=[0, 100]), title="% within panel range"),
            yOffset=alt.YOffset("Band:N", sort=["Exact range", "With tolerance"]),
            color=alt.Color("Band:N", scale=alt.Scale(range=[ICE, ICE_LIGHT]),
                            legend=None),
            tooltip=["Event", "Measure", alt.Tooltip("Percent:Q", format=".1f")],
        )
        .properties(height=alt.Step(22))
    )


def legend(items):
    dots = " ".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:16px">'
        f'<span style="width:11px;height:11px;border-radius:{r};background:{c};margin-right:6px"></span>{t}</span>'
        for t, c, r in items
    )
    st.markdown(f'<div style="font-size:0.85rem;opacity:0.8;margin-bottom:1.25rem">{dots}</div>',
                unsafe_allow_html=True)


if view == "Overview":
    legend([("Exact panel range", ICE, "2px"), ("With tolerance (GOE ±1, components ±0.25)", ICE_LIGHT, "2px")])
    c1, c2 = st.columns([1.35, 1])
    c1.altair_chart(range_bars("GOEs", "GOE % in range", "GOE % ±1", True), **STRETCH)
    c2.altair_chart(range_bars("Components", "Comp % in range", "Comp % ±0.25", False), **STRETCH)

    st.dataframe(
        summary, hide_index=True, **STRETCH,
        column_config={
            c: st.column_config.ProgressColumn(c, format="%.1f%%", min_value=0, max_value=100)
            for c in ["GOE % in range", "GOE % ±1", "Comp % in range", "Comp % ±0.25"]
        },
    )

if view == "By event":
    event_names = [df.iloc[0]["Skater"] for df in results]
    choice = st.selectbox("Event", event_names)
    df = results[event_names.index(choice)]

    pts = component_points(df)
    lo = math.floor((min(pts["Panel min"].min(), pts["Judge"].min()) - 0.25) * 2) / 2
    hi = math.ceil((max(pts["Panel max"].max(), pts["Judge"].max()) + 0.25) * 2) / 2
    st.markdown("**Components: my mark (dot) vs. rest of panel (bar)**")
    legend([("In range", ICE, "50%"), ("Within ±0.25", NEAR, "50%"),
            ("Outside ±0.25", OUT, "50%"), ("Rest of panel", ICE_LIGHT, "2px")])
    # One faceted chart with a fixed-width name column and equal, fixed-size panels,
    # so the three components line up and look the same in every event.
    comp_order = ["Composition", "Presentation", "Skating Skills"]
    base = alt.Chart().encode(
        y=alt.Y("Skater:N", sort=None, title=None,
                axis=alt.Axis(labelAlign="left", labelPadding=150, labelLimit=144, ticks=False))
    )
    ranges = base.mark_rule(strokeWidth=7, opacity=0.35, color=ICE, strokeCap="round").encode(
        x=alt.X("Panel min:Q", scale=alt.Scale(domain=[lo, hi]), title=None), x2="Panel max:Q",
    )
    marks = base.mark_point(filled=True, size=90, opacity=1).encode(
        x="Judge:Q",
        color=alt.Color("Status:N", scale=alt.Scale(domain=["In range", "Within ±0.25", "Outside ±0.25"],
                                                    range=[ICE, NEAR, OUT]),
                        legend=None),
        tooltip=["Skater", "Component", "Judge", "Panel min", "Panel max", "Status"],
    )
    comp_chart = (
        alt.layer(ranges, marks, data=pts)
        .properties(width=250, height=alt.Step(34))
        .facet(
            column=alt.Column("Component:N", sort=comp_order, title=None,
                              header=alt.Header(labelFontSize=14, labelFontWeight="bold",
                                                labelAnchor="start", labelOrient="top")),
            spacing=28,
        )
    )
    st.altair_chart(comp_chart, **CONTENT)

    st.markdown("**GOEs: my mark (dot) vs. rest of panel (bar), per element**")
    raw_el = df.attrs.get("elements")
    elements = raw_el if isinstance(raw_el, pd.DataFrame) else pd.DataFrame(raw_el or [])
    if elements.empty:
        st.info("No element detail for this event. If this is an older saved run, tick "
                "“Re-fetch from the results site” and run it again.")
    else:
        el = elements.copy()
        el["Status"] = [
            "In range" if lo <= g <= hi else ("Within ±1" if lo - 1 <= g <= hi + 1 else "Outside ±1")
            for lo, hi, g in zip(el["Panel min"], el["Panel max"], el["My GOE"])
        ]
        el["Label"] = el["#"].astype(int).astype(str) + ". " + el["Element"]
        legend([("In range", ICE, "50%"), ("Within ±1", NEAR, "50%"),
                ("Outside ±1", OUT, "50%"), ("Rest of panel", ICE_LIGHT, "2px")])
        only_out = st.checkbox("Only show skaters with a GOE outside the panel range")

        skaters = list(dict.fromkeys(el["Skater"]))
        if only_out:
            skaters = [k for k in skaters if (el.loc[el["Skater"] == k, "Status"] != "In range").any()]
            if not skaters:
                st.success("Every GOE in this event is inside the rest of the panel's range.")

        status_scale = alt.Scale(domain=["In range", "Within ±1", "Outside ±1"], range=[ICE, NEAR, OUT])
        grid = st.columns(2)
        for k, skater in enumerate(skaters):
            sub = el[el["Skater"] == skater]
            row = df[df["Skater"] == skater]
            in_pct = row["GOE % w/in Range"].iloc[0] if len(row) else ""
            base = alt.Chart(sub, title=alt.TitleParams(f"{skater}  ·  {in_pct} in range", anchor="start",
                                                        fontSize=13)).encode(
                y=alt.Y("Label:N", sort=None, title=None,
                  axis=alt.Axis(labelAlign="left", labelPadding=130, labelLimit=124, ticks=False))
            )
            ranges = base.mark_rule(strokeWidth=7, opacity=0.35, color=ICE, strokeCap="round").encode(
                x=alt.X("Panel min:Q", scale=alt.Scale(domain=[-5.5, 5.5]),
                        axis=alt.Axis(values=list(range(-5, 6)), title=None)),
                x2="Panel max:Q",
            )
            marks = base.mark_point(filled=True, size=80, opacity=1).encode(
                x="My GOE:Q",
                color=alt.Color("Status:N", scale=status_scale, legend=None),
                tooltip=["Element", "My GOE", "Panel min", "Panel max", "Status"],
            )
            grid[k % 2].altair_chart((ranges + marks).properties(height=alt.Step(24)), **STRETCH)

    st.markdown("**Skater detail**")
    detail = df.iloc[1:].astype(object).where(df.iloc[1:].notna(), "").astype(str)
    st.dataframe(
        detail[["Skater", "# of GOEs", "# of GOEs w/in Range", "GOE % w/in Range", "GOE % w/in Range +/- 1",
                "Composition", "My Composition", "Presentation", "My Presentation",
                "Skating Skills", "My Skating Skills", "Component % w/in Range",
                "Component % w/in Range +/- .25"]],
        hide_index=True, **STRETCH,
    )

st.divider()
csv = analysis.combine_results(results).to_csv(index=False).encode("utf-8")
st.download_button(
    "Download full results (CSV)", csv,
    file_name=f"judge_range_{name.replace(' ', '_')}.csv", mime="text/csv",
)
