# RI Housing Report

A command-line report on Rhode Island housing. It covers the state budget and funding sources, the number of units built (Census building permits), the laws that affect nonprofit revenue and production, and a priced list of policy tweaks. It uses the Python standard library only.

```bash
python3 tools/ri_housing_report/report.py              # Census permits (no key) + curated data
python3 tools/ri_housing_report/report.py --ai         # + Gemini/Google Search budget lookup
python3 tools/ri_housing_report/report.py --since 2000 # longer permit history
python3 tools/ri_housing_report/report.py --offline    # curated data only
```

The report is printed to the terminal and saved to `out/report.md` and `out/report.json`.

## Data sources

| Source | Key (in root `.env`) | Provides |
|---|---|---|
| Census Building Permits Survey | none | Units permitted per year by building size |
| Census ACS 1-year | `CENSUS_API_KEY` (free) | Housing units, median rent and income, rent burden |
| HUD USER API | `HUD_API_TOKEN` (free) | Fair Market Rents across RI areas |
| Gemini + Google Search | `GOOGLE_API_KEY` | Current enacted-budget housing lines, with source links |
| `policy_data.json` | — | Benchmarks, funding sources, laws, tweak parameters |

The Gemini output is labeled as unverified in the report. Check its figures against the enacted budget at omb.ri.gov before publishing them. In `policy_data.json`, entries marked `verify` need the same check.

## Changing assumptions

Edit `policy_data.json`. `benchmarks` drives every derived number. Each entry in `tweaks` names a `calc` (see `Model.price` in `report.py`) and its `params`, so you can add a tweak or change an assumption without touching code.
