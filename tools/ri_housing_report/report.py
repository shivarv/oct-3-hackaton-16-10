"""Rhode Island housing report: budget, production, laws, and policy tweaks.

Usage (from repo root):
    python tools/ri_housing_report/report.py              # live Census permits + curated data
    python tools/ri_housing_report/report.py --ai         # also look up the budget with Gemini
    python tools/ri_housing_report/report.py --since 2010 --out /tmp/ri

Writes report.md and report.json to --out (default tools/ri_housing_report/out/)
and prints the markdown to the terminal.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import sources

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


# --------------------------------------------------------------------------- #
# Minimal markdown -> HTML for the subset render() emits
# (headings, tables, bullets, blockquotes, bold, italics, rules, links)
# --------------------------------------------------------------------------- #
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rhode Island Housing Report</title>
<style>
:root{{--bg:#f6f7f8;--surface:#fff;--fg:#1b2430;--muted:#55606e;--rule:#d5dae0;--accent:#1f5f6b;--warn:#fbf1dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12171d;--surface:#1a2129;--fg:#e4e8ec;--muted:#9aa5b1;--rule:#2e3843;
--accent:#6fb8c4;--warn:#33291a;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:72rem;margin:0 auto;padding:2rem 16px 4rem}}
h1{{font-size:2rem;margin:0 0 .25rem;border-bottom:2px solid var(--fg);padding-bottom:.6rem}}
h2{{font-size:1.35rem;margin:2.4rem 0 .8rem;padding-top:.8rem;border-top:1px solid var(--rule);color:var(--accent)}}
h3{{font-size:1.1rem;margin:1.6rem 0 .5rem}}
.tbl{{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);margin:.8rem 0 1.2rem}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{padding:.5rem .7rem;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}}
th{{background:var(--bg);font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
blockquote{{margin:.8rem 0;padding:.7rem 1rem;background:var(--warn);border-left:3px solid #c08a1e}}
ul{{padding-left:1.2rem}} li{{margin:.25rem 0}} em{{color:var(--muted)}}
a{{color:var(--accent)}} hr{{border:0;border-top:1px solid var(--rule);margin:2rem 0 1rem}}
</style></head><body><main>
{body}
</main></body></html>"""


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])_(.+?)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return re.sub(r"(https?://[^\s|<)]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)


def md_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            align = ["r" if c.endswith(":") else "" for c in rows[1]] if len(rows) > 1 else []
            head, body = rows[0], rows[2:]
            th = "".join(f'<th class="{align[j] if j < len(align) else ""}">{_inline(c)}</th>' for j, c in enumerate(head))
            trs = "".join(
                "<tr>" + "".join(f'<td class="{align[j] if j < len(align) else ""}">{_inline(c)}</td>'
                                 for j, c in enumerate(r)) + "</tr>" for r in body)
            out.append(f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append(f"<ul>{''.join(items)}</ul>")
            continue
        if m := re.match(r"(#{1,3}) (.*)", line):
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    return PAGE.format(body="\n".join(out))


def usd(n: float | None) -> str:
    if n is None:
        return "—"
    if abs(n) >= 1e9:
        return f"${n / 1e9:,.2f}B"
    if abs(n) >= 1e6:
        return f"${n / 1e6:,.1f}M"
    return f"${n:,.0f}"


# --------------------------------------------------------------------------- #
# Policy-tweak model
# --------------------------------------------------------------------------- #
class Model:
    """Derives planning constants from the benchmarks and prices each tweak."""

    def __init__(self, b: dict):
        self.b = b
        self.carry_per_unit_month = b["carry_cost_per_layer_per_unit"] / b["months_added_per_layer"]
        self.pipeline_units = b["pipeline_savings_per_month_saved"] / self.carry_per_unit_month
        self.gap_per_unit = b["tdc_per_subsidized_unit"] * b["public_subsidy_share"]

    def price(self, calc: str, p: dict) -> dict:
        b, gap = self.b, self.gap_per_unit
        per_month = b["pipeline_savings_per_month_saved"]
        if calc == "cadence":
            saved = p["months_saved"] * per_month
            return {"savings_usd": saved, "units": saved / gap,
                    "detail": f"{p['months_saved']} months saved x {usd(per_month)}/month across the pipeline"}
        if calc == "layer_removed":
            saved = p["layers_removed"] * self.pipeline_units * b["carry_cost_per_layer_per_unit"]
            return {"savings_usd": saved, "units": saved / gap,
                    "detail": f"{p['layers_removed']} layer(s) x {self.pipeline_units:,.0f} units x "
                              f"{usd(b['carry_cost_per_layer_per_unit'])}"}
        if calc == "permitting":
            lo, hi = b["units_from_25pct_permitting_cut"]
            return {"units": (lo + hi) / 2, "units_range": [lo, hi], "savings_usd": None,
                    "detail": f"{lo}-{hi} units/yr with no new subsidy (benchmark); worth "
                              f"{usd(lo * gap)}-{usd(hi * gap)} of subsidy at {usd(gap)}/unit"}
        if calc == "churn":
            saved = p["churn_months_removed"] * p["share_of_projects_with_churn"] * per_month
            return {"savings_usd": saved, "units": saved / gap,
                    "detail": f"{p['churn_months_removed']} month x {p['share_of_projects_with_churn']:.0%} "
                              f"of projects x {usd(per_month)}"}
        if calc == "zoning_stretch":
            new_gap = gap - p["tdc_reduction_per_unit"] * b["tdc_to_gap_pass_through"]
            before, after = p["pool_usd"] / gap, p["pool_usd"] / new_gap
            return {"savings_usd": None, "units": after - before,
                    "detail": f"gap {usd(gap)} -> {usd(new_gap)}/unit; {usd(p['pool_usd'])} funds "
                              f"{before:,.0f} -> {after:,.0f} units"}
        if calc == "free_land":
            land = p["units_per_site"] * p["land_cost_per_unit"]
            return {"savings_usd": land, "units": p["units_per_site"],
                    "detail": f"{usd(land)} land avoided per {p['units_per_site']}-unit site (per site, not per year)"}
        if calc in ("tax_assessment", "operating_subsidy"):
            annual = p.get("tax_savings_per_unit_per_year") or p["subsidy_per_unit_per_year"]
            debt = annual / p["dscr"] / p["debt_constant"]
            return {"savings_usd": None, "units": None,
                    "detail": f"{usd(annual)}/unit/yr of NOI supports ~{usd(debt)}/unit more permanent debt "
                              f"(less gap subsidy needed)"}
        if calc == "preservation":
            cost = b["tdc_per_subsidized_unit"] * p["preservation_cost_ratio"]
            per_10m_new = 10e6 / gap
            per_10m_pres = 10e6 / (cost * b["public_subsidy_share"])
            return {"savings_usd": None, "units": None,
                    "detail": f"$10M of subsidy keeps ~{per_10m_pres:,.0f} existing units vs ~{per_10m_new:,.0f} new"}
        return {"savings_usd": None, "units": None, "detail": p.get("note", "")}


# --------------------------------------------------------------------------- #
# Production analysis
# --------------------------------------------------------------------------- #
def analyze_permits(rows: list[dict], population: int, units_lo_hi: list[int]) -> dict:
    if not rows:
        return {}
    latest = rows[-1]
    last5 = rows[-5:]
    avg5 = sum(r["total_units"] for r in last5) / len(last5)
    peak = max(rows, key=lambda r: r["total_units"])
    mid = sum(units_lo_hi) / 2
    return {
        "latest_year": latest["year"],
        "latest_total": latest["total_units"],
        "latest_multifamily_share": latest["units_5_plus"] / latest["total_units"] if latest["total_units"] else 0,
        "per_1000_residents": latest["total_units"] / population * 1000,
        "avg_last_5": avg5,
        "peak_year": peak["year"],
        "peak_total": peak["total_units"],
        "permitting_reform_uplift_pct": mid / latest["total_units"] if latest["total_units"] else 0,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render(ctx: dict) -> str:
    m: Model = ctx["model"]
    data, permits, stats = ctx["data"], ctx["permits"], ctx["permit_stats"]
    out: list[str] = []
    w = out.append

    w("# Rhode Island Housing Report")
    w(f"_Generated {ctx['generated']}. Live data: {', '.join(ctx['live_sources']) or 'none'}._\n")

    w("## Data source status\n")
    w("| Source | Status | Detail |")
    w("|---|---|---|")
    icon = {"ok": "✅ Working", "off": "⚪ Not enabled", "fail": "❌ Failed"}
    for name, state, note in ctx["status"]:
        w(f"| {name} | {icon[state]} | {note} |")
    w("")

    # 1. Budget
    w("## 1. State budget and funding sources\n")
    w("| Source | Level | Amount | Year | Use | Confidence |")
    w("|---|---|---|---|---|---|")
    for f in data["funding_sources"]:
        w(f"| {f['name']} | {f['level']} | {usd(f['amount_usd'])} | {f['year'] or '—'} | {f['use']} | {f['confidence']} |")
    bench = data["benchmarks"]
    w(f"\n**Cost benchmarks:** {usd(bench['tdc_per_subsidized_unit'])} per subsidized unit, "
      f"{bench['public_subsidy_share']:.0%} public share = **{usd(m.gap_per_unit)} subsidy per unit**. "
      f"{bench['multi_layer_share']:.0%}+ of projects use several non-tax-credit layers; each adds "
      f"{bench['months_added_per_layer']} months and {usd(bench['carry_cost_per_layer_per_unit'])}/unit.")
    w(f"\n**Derived:** carry is about {usd(m.carry_per_unit_month)}/unit/month, which implies "
      f"~{m.pipeline_units:,.0f} units in predevelopment per year.")
    bonds = sum(f["amount_usd"] or 0 for f in data["funding_sources"] if "Bond" in f["name"] and f["year"] and f["year"] >= 2024)
    if bonds:
        w(f"At {usd(m.gap_per_unit)}/unit, the {usd(bonds)} 2024 bond covers the gap on ~{bonds / m.gap_per_unit:,.0f} units.")

    ai = ctx.get("ai_budget")
    if ai:
        w("\n### Budget lookup (Gemini + Google Search, unverified)\n")
        if "error" in ai:
            w(f"> Lookup failed: {ai['error']}")
        else:
            w(f"Fiscal year: **{ai.get('fiscal_year', '?')}**; total state budget: **{usd(ai.get('total_state_budget_usd'))}**\n")
            w("| Item | Amount | Fund | Description | Source |")
            w("|---|---|---|---|---|")
            for it in ai.get("housing_items", []):
                w(f"| {it.get('name')} | {usd(it.get('amount_usd'))} | {it.get('fund_type', '')} | "
                  f"{it.get('description', '')} | {it.get('source_url', '')} |")
            if ai.get("notes"):
                w(f"\n{ai['notes']}")
            if ai.get("grounding_sources"):
                w(f"\nGrounding sources: {len(ai['grounding_sources'])} pages ({ai.get('model')}). "
                  "Check every figure against the enacted budget before use.")

    # 2. Production
    w("\n## 2. Housing production (Census Building Permits Survey)\n")
    if permits:
        w("| Year | 1-unit | 2-unit | 3–4 unit | 5+ unit | Total units |")
        w("|---|--:|--:|--:|--:|--:|")
        for r in permits:
            w(f"| {r['year']} | {r['units_1']:,} | {r['units_2']:,} | {r['units_3_4']:,} | {r['units_5_plus']:,} | **{r['total_units']:,}** |")
        s = stats
        w(f"\n- **{s['latest_year']}:** {s['latest_total']:,} units permitted "
          f"({s['per_1000_residents']:.1f} per 1,000 residents); {s['latest_multifamily_share']:.0%} in 5+ unit buildings.")
        w(f"- Five-year average: {s['avg_last_5']:,.0f} units/yr. Peak in this window: {s['peak_total']:,} ({s['peak_year']}).")
        w(f"- The 25% permitting-delay cut (600–700 units/yr) would raise output by about "
          f"**{s['permitting_reform_uplift_pct']:.0%}** over {s['latest_year']}.")
        w("- Permits count all units, market-rate and affordable. For subsidized completions, use the RIHousing "
          "annual report or HUD's LIHTC database.")
    else:
        w("_Permit data unavailable (offline or fetch failed)._")

    acs, fmr = ctx.get("acs"), ctx.get("fmr")
    if acs or fmr:
        w("\n### Market context\n")
    if acs:
        w(f"- ACS {acs['year']}: {acs.get('housing_units', 0):,} housing units; median gross rent "
          f"{usd(acs.get('median_gross_rent'))}; median household income {usd(acs.get('median_household_income'))}.")
        if "rent_burdened_share" in acs:
            w(f"- {acs['rent_burdened_share']:.0%} of renters pay 30%+ of income on rent; "
              f"{acs['severely_burdened_share']:.0%} pay 50%+.")
    if fmr:
        w(f"- HUD FY{fmr['year']} 2BR Fair Market Rent across {fmr['areas']} RI areas: "
          f"{usd(fmr['two_br_min'])}–{usd(fmr['two_br_max'])} (median {usd(fmr['two_br_median'])}).")

    # 3. Laws
    w("\n## 3. Laws and features that affect nonprofit revenue and units built\n")
    label = {"production": "Units built", "nonprofit_revenue": "Nonprofit revenue", "both": "Both"}
    w("| Law / feature | Affects | How it works | Impact | Confidence |")
    w("|---|---|---|---|---|")
    for law in data["laws"]:
        w(f"| {law['name']} | {label[law['affects']]} | {law['mechanism']} | {law['impact']} | {law['confidence']} |")

    # 4. Tweaks
    w("\n## 4. Tweaks to build more housing or improve project finances\n")
    laws = {law["id"]: law["name"] for law in data["laws"]}
    w("| Factor | Tweak | Mechanism | Savings | Units (yr or per site) | Basis |")
    w("|---|---|---|--:|--:|---|")
    for t in ctx["priced_tweaks"]:
        r = t["result"]
        units = f"{r['units_range'][0]}–{r['units_range'][1]}" if r.get("units_range") else (
            f"~{r['units']:,.0f}" if r.get("units") else "—")
        note = f" (overlaps with {t['overlaps_with']}; do not add)" if t.get("overlaps_with") else ""
        w(f"| {laws.get(t['factor'], t['factor'])} | {t['tweak']} | {t['mechanism']} | "
          f"{usd(r.get('savings_usd'))} | {units} | {r['detail']}{note} |")

    w("\n---\n_Confidence: `high` = established statute or program; `verify` = check against the cited source; "
      "`fill-in` = enter from the enacted budget. Edit `policy_data.json` to update figures._")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, default=2015, help="first permit year (files exist from 2000)")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--ai", action="store_true", help="look up current budget figures with Gemini + Google Search")
    ap.add_argument("--offline", action="store_true", help="skip all network calls")
    ap.add_argument("--html", action="store_true", help="open the report in your web browser")
    args = ap.parse_args()

    sources.load_env(REPO_ROOT / ".env")
    data = json.loads((HERE / "policy_data.json").read_text())
    model = Model(data["benchmarks"])
    live: list[str] = []
    # (source, state, note) where state is ok | off | fail
    status: list[tuple[str, str, str]] = []

    permits, acs, fmr, ai_budget = [], None, None, None
    if args.offline:
        status.append(("All live sources", "off", "--offline: curated data only"))
    else:
        try:
            permits = sources.fetch_permits(args.since)
            live.append("Census BPS")
            status.append(("Census building permits", "ok", f"{len(permits)} years loaded"))
        except Exception as e:  # noqa: BLE001 - report continues with curated data
            print(f"warning: permit fetch failed: {e}", file=sys.stderr)
            status.append(("Census building permits", "fail", str(e)[:160]))
        if acs := sources.fetch_acs():
            live.append("Census ACS")
            status.append(("Census ACS", "ok", f"{acs['year']} 1-year estimates"))
        else:
            has_key = bool(os.environ.get("CENSUS_API_KEY"))
            status.append(("Census ACS", "fail" if has_key else "off",
                           "key set but request failed" if has_key else "add CENSUS_API_KEY to .env"))
        if fmr := sources.fetch_hud_fmr():
            live.append("HUD FMR")
            status.append(("HUD Fair Market Rents", "ok", f"FY{fmr['year']}, {fmr['areas']} areas"))
        else:
            has_key = bool(os.environ.get("HUD_API_TOKEN"))
            status.append(("HUD Fair Market Rents", "fail" if has_key else "off",
                           "token set but request failed" if has_key else "add HUD_API_TOKEN to .env"))
        if args.ai:
            ai_budget = sources.fetch_budget_via_gemini()
            if ai_budget is None:
                print("warning: --ai needs GOOGLE_API_KEY (or GEMINI_API_KEY) in .env", file=sys.stderr)
                status.append(("Gemini budget lookup", "fail", "add GOOGLE_API_KEY to .env"))
            elif "error" in ai_budget:
                status.append(("Gemini budget lookup", "fail", ai_budget["error"][:160]))
            else:
                live.append("Gemini budget lookup")
                status.append(("Gemini budget lookup", "ok", f"{len(ai_budget.get('housing_items', []))} budget lines"))
        else:
            status.append(("Gemini budget lookup", "off", "run with --ai"))

    priced = [{**t, "result": model.price(t["calc"], t["params"])} for t in data["tweaks"]]
    ctx = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "live_sources": live,
        "status": status,
        "data": data,
        "model": model,
        "permits": permits,
        "permit_stats": analyze_permits(
            permits, data["benchmarks"]["ri_population_2020_census"], data["benchmarks"]["units_from_25pct_permitting_cut"]
        ),
        "acs": acs,
        "fmr": fmr,
        "ai_budget": ai_budget,
        "priced_tweaks": priced,
    }

    md = render(ctx)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(md)
    dump = {k: v for k, v in ctx.items() if k not in ("model", "data")}
    dump["derived"] = {"carry_per_unit_month": model.carry_per_unit_month,
                       "pipeline_units": model.pipeline_units, "gap_per_unit": model.gap_per_unit}
    (args.out / "report.json").write_text(json.dumps(dump, indent=2, default=str))
    html_path = args.out / "report.html"
    html_path.write_text(md_to_html(md))
    print(md)
    print(f"\nSaved report.md, report.json and report.html to {args.out}", file=sys.stderr)
    if args.html:
        webbrowser.open(html_path.resolve().as_uri())
        print(f"Opened {html_path} in your browser", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
