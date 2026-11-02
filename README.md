# Judge Range Analysis

As a US Figure Skating judge, I wanted a clear way to check how consistent
my marks are with the rest of the panel. This app pulls a competition's
public score sheets and measures how often my scores fall within the range
set by the other judges.

## What it measures

For every skater I judged at a competition:

- **Grades of Execution (GOEs):** the share of my element marks that fall
  within the other judges' lowest-to-highest range, and within that range
  ±1.
- **Program components** (Composition, Presentation, Skating Skills): the
  share of my marks within the other judges' range, and within ±0.25.

Results are shown by event and by skater, with charts showing where each of
my marks sits relative to the panel.

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
