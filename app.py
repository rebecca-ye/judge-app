"""
Streamlit UI for the judge range analysis.

Run locally:   streamlit run app.py
Password:      set APP_PASSWORD in .streamlit/secrets.toml (or in the host's secrets settings).
"""

import hmac

import altair as alt
import pandas as pd
import streamlit as st

import analysis

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
    </style>
    """,
    unsafe_allow_html=True,
)

ICE = "#2E6FD8"
ICE_LIGHT = "#9EC3F5"
OUT = "#D9534F"


# ---------- Private access ----------
def get_password():
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
            tj = float(r[f"TJ {comp}"])
            rows.append({
                "Skater": r["Skater"], "Component": comp, "Panel min": lo, "Panel max": hi,
                "Judge": tj, "Status": "In range" if lo <= tj <= hi else "Outside range",
            })
    return pd.DataFrame(rows)


# ---------- Page ----------
st.title("⛸️ Judge Range Analysis")
st.markdown(
    '<p class="subtle">How often a judge\'s GOEs and program components fall inside the rest of the panel\'s range.</p>',
    unsafe_allow_html=True,
)

with st.form("inputs"):
    c_url, c_name, c_btn = st.columns([3, 1.4, 1], vertical_alignment="bottom")
    comp_url = c_url.text_input(
        "Competition results URL",
        placeholder="https://ijs.usfigureskating.org/leaderboard/results/2025/36167/index.asp",
    )
    judge_name = c_name.text_input("Official's full name", placeholder="Rebecca Ye")
    submitted = c_btn.form_submit_button("Run analysis", type="primary", width="stretch")

if submitted:
    if not comp_url.strip() or not judge_name.strip():
        st.error("Enter both a URL and a name.")
    else:
        try:
            out = run_analysis(comp_url.strip(), judge_name.strip())
            st.session_state["result"] = (judge_name.strip(), *out)
        except Exception as e:
            st.error(f"Couldn't read that competition page: {e}")

if "result" not in st.session_state:
    st.info("Enter a competition URL and a judge's name above, then click Run analysis. Results are cached for an hour.")
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

tab_overview, tab_events = st.tabs(["Overview", "By event"])


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
    st.markdown(f'<div style="font-size:0.85rem;opacity:0.8">{dots}</div>', unsafe_allow_html=True)


with tab_overview:
    legend([("Exact panel range", ICE, "2px"), ("With tolerance (GOE ±1, components ±0.25)", ICE_LIGHT, "2px")])
    c1, c2 = st.columns([1.35, 1])
    c1.altair_chart(range_bars("GOEs", "GOE % in range", "GOE % ±1", True), width="stretch")
    c2.altair_chart(range_bars("Components", "Comp % in range", "Comp % ±0.25", False), width="stretch")

    st.dataframe(
        summary, hide_index=True, width="stretch",
        column_config={
            c: st.column_config.ProgressColumn(c, format="%.1f%%", min_value=0, max_value=100)
            for c in ["GOE % in range", "GOE % ±1", "Comp % in range", "Comp % ±0.25"]
        },
    )

with tab_events:
    event_names = [df.iloc[0]["Skater"] for df in results]
    choice = st.selectbox("Event", event_names)
    df = results[event_names.index(choice)]

    pts = component_points(df)
    lo = min(pts["Panel min"].min(), pts["Judge"].min()) - 0.25
    hi = max(pts["Panel max"].max(), pts["Judge"].max()) + 0.25
    st.markdown("**Components: judge's mark (dot) vs. rest of panel (bar)**")
    legend([("Judge in range", ICE, "50%"), ("Judge outside range", OUT, "50%"), ("Rest of panel", ICE_LIGHT, "2px")])
    cols = st.columns([1.35, 1, 1])
    for i, comp in enumerate(["Composition", "Presentation", "Skating Skills"]):
        sub = pts[pts["Component"] == comp]
        base = alt.Chart(sub, title=comp).encode(
            y=alt.Y("Skater:N", sort=None, title=None,
                    axis=alt.Axis(labels=i == 0, ticks=i == 0, labelLimit=160))
        )
        ranges = base.mark_rule(strokeWidth=7, opacity=0.35, color=ICE, strokeCap="round").encode(
            x=alt.X("Panel min:Q", scale=alt.Scale(domain=[lo, hi]), title=None), x2="Panel max:Q",
        )
        marks = base.mark_point(filled=True, size=90, opacity=1).encode(
            x="Judge:Q",
            color=alt.Color("Status:N", scale=alt.Scale(domain=["In range", "Outside range"], range=[ICE, OUT]),
                            legend=None),
            tooltip=["Skater", "Judge", "Panel min", "Panel max"],
        )
        cols[i].altair_chart(
            (ranges + marks).properties(height=alt.Step(34)), width="stretch"
        )

    st.markdown("**Skater detail**")
    detail = df.iloc[1:].astype(object).where(df.iloc[1:].notna(), "").astype(str)
    st.dataframe(
        detail[["Skater", "# of GOEs", "# of GOEs w/in Range", "GOE % w/in Range", "GOE % w/in Range +/- 1",
                "Composition", "TJ Composition", "Presentation", "TJ Presentation",
                "Skating Skills", "TJ Skating Skills", "Component % w/in Range",
                "Component % w/in Range +/- .25"]],
        hide_index=True, width="stretch",
    )

st.divider()
csv = analysis.combine_results(results).to_csv(index=False).encode("utf-8")
st.download_button(
    "Download full results (CSV)", csv,
    file_name=f"judge_range_{name.replace(' ', '_')}.csv", mime="text/csv",
)
