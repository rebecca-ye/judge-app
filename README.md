# Judge Range Analysis

The goal is to provide an easy way for US Figure Skating judges to check how consistent
their marks are with the rest of the panel. This app pulls a competition's
public score sheets and measures how often a specified judge's scores fall within the range
across the other judges.

## What it measures

For every skater the specified judge (call them J) judged at a competition:

- **Grades of Execution (GOEs):** the share of J's element marks that fall
  within the other judges' lowest-to-highest range, and within that range
  ±1.
- **Program components** (Composition, Presentation, Skating Skills): the
  share of J's marks within the other judges' range, and within ±0.25.

Results are shown by event and by skater, with charts showing where each of
J's marks sits relative to the panel.

## How it works

1. Enter a competition results URL and a judge's name.
2. The app finds each event where that judge served, reads the judges'
   detail sheets, and compares the judge's marks with the rest of the panel.
3. Results can be saved and reopened later.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

The analysis can also be run without the interface: `python analysis.py`.

To require a password, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and set `APP_PASSWORD`.

## Files

- `analysis.py`: scrapes the score sheets and calculates the statistics
- `app.py`: the Streamlit interface and charts

## Author

Rebecca Ye
