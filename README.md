# Judge Range Analysis (Streamlit)

```
analysis.py                    # your original script, lightly refactored (still runs on its own)
app.py                         # the Streamlit UI
requirements.txt
.streamlit/config.toml         # theme
.streamlit/secrets.toml.example
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The old command-line version still works: `python analysis.py`.

## Private access

- **Password:** copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and set `APP_PASSWORD`. If no password is set, the app opens without one, which is handy locally.
- **Streamlit Community Cloud:** push the folder to a GitHub repo, deploy it, paste `APP_PASSWORD = "..."` into the app's **Secrets** settings, and set the app to private with an invite list under **Sharing**. You can use both together.

## Changes to `judge_panel_analysis.py` (now `analysis.py`)

The scoring logic in `compute_skater_stats` is unchanged.

1. **`find_officials_table`**: matches any table whose class contains `officials` instead of the four hard-coded classes (`officials ladies/men/pairs/team`). New class names such as `officials women` are no longer silently skipped.
2. **`pd.read_html(...)` (two calls in `process_event`)**: the HTML is wrapped in `StringIO(...)`. Newer pandas no longer accepts a raw HTML string. Adds `from io import StringIO`.
3. **`requests.get(...)` (three calls)**: added `timeout=30` (`REQUEST_TIMEOUT`) so a stalled page can't hang the app.
4. **Skater name alignment bug in `process_event`**: names used to be assigned with `skater_names[:len(stats)]`. If a skater in the middle was skipped, every later skater got the previous skater's name. Names are now collected inside the loop alongside each successful stats row.
5. **Skipped-skater count**: `process_event` counts skipped score sheets and stores the number in `stats.attrs["skipped"]`, so the UI can warn about it. The return value is otherwise the same.
6. **`main()` split into reusable pieces**:
   - `get_event_links(comp_url)` returns `(base_url, event_links)`. This is the old first half of `main`.
   - `combine_results(event_results)` builds the final stacked table with spacer rows, which is the old CSV layout.
   - `COLUMNS` is the column list that used to be defined inline in `main`.
   - `main()` now calls these functions and still prints each event and writes `judge_range_analysis.csv`.
