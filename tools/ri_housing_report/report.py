"""Rhode Island housing report: budget, production, laws, and policy tweaks.

Usage (from repo root):
    python3 tools/ri_housing_report/report.py --html       # build the dashboard and open it in the browser
    python3 tools/ri_housing_report/report.py --ai --html  # also look up the budget with Gemini
    python3 tools/ri_housing_report/report.py --since 2000 # longer permit history

Writes report.md, report.json and report.html (dashboard) to --out
(default tools/ri_housing_report/out/) and prints the markdown to the terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import sources

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def usd(n: float | None) -> str:
    if n is None:
        return "—"
    if abs(n) >= 1e9:
        return f"${n / 1e9:,.2f}B"
    if abs(n) >= 1e6:
        return f"${n / 1e6:,.1f}M"
    return f"${n:,.0f}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.0%}" if abs(x) >= 0.1 else f"{x:+.1%}"


# --------------------------------------------------------------------------- #
# Policy-tweak model
# --------------------------------------------------------------------------- #
class Model:
    """Derives planning constants from the benchmarks and prices each tweak.

    Each priced tweak reports, where it applies:
      units        added (or subsidy-equivalent) units; per year unless per_site
      stretch_pct  how many more units the same public dollars fund
    units_pct (units / statewide annual permits) is added later, once permit data is known.
    """

    def __init__(self, b: dict):
        self.b = b
        self.carry_per_unit_month = b["carry_cost_per_layer_per_unit"] / b["months_added_per_layer"]
        self.pipeline_units = b["pipeline_savings_per_month_saved"] / self.carry_per_unit_month
        self.gap_per_unit = b["tdc_per_subsidized_unit"] * b["public_subsidy_share"]
        self.pipeline_subsidy = self.pipeline_units * self.gap_per_unit

    @staticmethod
    def _stretch_from_gap_cut(r: float) -> float:
        # Cutting the per-unit gap by r lets the same dollars fund 1/(1-r) as many units.
        return 1 / (1 - r) - 1

    def price(self, calc: str, p: dict) -> dict:
        b, gap = self.b, self.gap_per_unit
        per_month = b["pipeline_savings_per_month_saved"]
        res: dict = {"savings_usd": None, "units": None, "stretch_pct": None, "per_site": False, "one_time": False}
        if calc in ("cadence", "layer_removed", "churn"):
            if calc == "cadence":
                saved = p["months_saved"] * per_month
                res["detail"] = f"{p['months_saved']} months saved x {usd(per_month)}/month across the pipeline"
            elif calc == "layer_removed":
                saved = p["layers_removed"] * self.pipeline_units * b["carry_cost_per_layer_per_unit"]
                res["detail"] = (f"{p['layers_removed']} layer(s) x {self.pipeline_units:,.0f} units x "
                                 f"{usd(b['carry_cost_per_layer_per_unit'])}")
            else:
                saved = p["churn_months_removed"] * p["share_of_projects_with_churn"] * per_month
                res["detail"] = (f"{p['churn_months_removed']} month x {p['share_of_projects_with_churn']:.0%} "
                                 f"of projects x {usd(per_month)}")
            res.update(savings_usd=saved, units=saved / gap, stretch_pct=saved / self.pipeline_subsidy)
        elif calc == "permitting":
            lo, hi = b["units_from_25pct_permitting_cut"]
            res.update(units=(lo + hi) / 2, units_range=[lo, hi],
                       detail=f"{lo}-{hi} units/yr with no new subsidy (benchmark); worth "
                              f"{usd(lo * gap)}-{usd(hi * gap)} of subsidy at {usd(gap)}/unit")
        elif calc == "zoning_stretch":
            new_gap = gap - p["tdc_reduction_per_unit"] * b["tdc_to_gap_pass_through"]
            before, after = p["pool_usd"] / gap, p["pool_usd"] / new_gap
            res.update(units=after - before, stretch_pct=after / before - 1, one_time=True,
                       detail=f"gap {usd(gap)} -> {usd(new_gap)}/unit; {usd(p['pool_usd'])} funds "
                              f"{before:,.0f} -> {after:,.0f} units")
        elif calc == "free_land":
            land = p["units_per_site"] * p["land_cost_per_unit"]
            r = p["land_cost_per_unit"] * b["tdc_to_gap_pass_through"] / gap
            res.update(savings_usd=land, units=p["units_per_site"], per_site=True,
                       stretch_pct=self._stretch_from_gap_cut(r),
                       detail=f"{usd(land)} land avoided per {p['units_per_site']}-unit site (per site, not per year)")
        elif calc in ("tax_assessment", "operating_subsidy"):
            annual = p.get("tax_savings_per_unit_per_year") or p["subsidy_per_unit_per_year"]
            debt = annual / p["dscr"] / p["debt_constant"]
            res.update(stretch_pct=self._stretch_from_gap_cut(debt / gap),
                       detail=f"{usd(annual)}/unit/yr of NOI supports ~{usd(debt)}/unit more permanent debt "
                              f"({debt / gap:.0%} smaller capital gap per affected unit)")
            if calc == "operating_subsidy":
                res["detail"] += "; costs the operating subsidy itself each year"
        elif calc == "preservation":
            cost = b["tdc_per_subsidized_unit"] * p["preservation_cost_ratio"]
            per_10m_new = 10e6 / gap
            per_10m_pres = 10e6 / (cost * b["public_subsidy_share"])
            res.update(stretch_pct=per_10m_pres / per_10m_new - 1,
                       detail=f"$10M of subsidy keeps ~{per_10m_pres:,.0f} existing units vs ~{per_10m_new:,.0f} new")
        else:
            res["detail"] = p.get("note", "")
        return res


# --------------------------------------------------------------------------- #
# Production analysis
# --------------------------------------------------------------------------- #
def analyze_permits(rows: list[dict], population: int, units_lo_hi: list[int]) -> dict:
    if not rows:
        return {}
    latest = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    last5 = rows[-5:]
    avg5 = sum(r["total_units"] for r in last5) / len(last5)
    peak = max(rows, key=lambda r: r["total_units"])
    mid = sum(units_lo_hi) / 2
    total = latest["total_units"]
    return {
        "latest_year": latest["year"],
        "latest_total": total,
        "change_vs_prev": (total / prev["total_units"] - 1) if prev and prev["total_units"] else None,
        "latest_multifamily_share": latest["units_5_plus"] / total if total else 0,
        "per_1000_residents": total / population * 1000,
        "avg_last_5": avg5,
        "peak_year": peak["year"],
        "peak_total": peak["total_units"],
        "permitting_reform_uplift_pct": mid / total if total else 0,
    }


def analyze_gap(pit: list[dict], stock: dict | None, gap_per_unit: float, bond: float) -> dict:
    """Homeless households vs. what current affordable production and the 2024 bond can house."""
    if not pit:
        return {}
    cur = pit[-1]
    households = cur.get("individuals", 0) + cur.get("family_households", 0)
    out = {
        "year": cur["year"],
        "people": cur["total"],
        "sheltered": cur.get("sheltered"),
        "unsheltered": cur.get("unsheltered"),
        "individuals": cur.get("individuals"),
        "family_households": cur.get("family_households"),
        "chronic_individuals": cur.get("chronic_individuals"),
        "households": households,
        "cost_to_house": households * gap_per_unit,
        "bond_units": bond / gap_per_unit,
    }
    out["bond_coverage"] = min(1.0, out["bond_units"] / households) if households else None
    out["unit_gap"] = max(0.0, households - out["bond_units"])
    out["funding_gap"] = out["unit_gap"] * gap_per_unit
    # Pre-pandemic baseline where available
    base = next((r for r in pit if r["year"] == 2019), pit[0])
    if base is not cur:
        out["baseline_year"] = base["year"]
        out["change_people"] = cur["total"] / base["total"] - 1
        if base.get("unsheltered"):
            out["change_unsheltered"] = cur["unsheltered"] / base["unsheltered"] - 1
        out["people_added_per_year"] = (cur["total"] - base["total"]) / (cur["year"] - base["year"])
    if stock and stock.get("lihtc_by_year"):
        recent = [r for r in stock["lihtc_by_year"] if r["year"] > stock["lihtc_by_year"][-1]["year"] - 5]
        out["lihtc_avg"] = sum(r["units"] for r in recent) / len(recent)
        out["lihtc_window"] = f"{recent[0]['year']}–{recent[-1]['year']} average, latest in HUD's database"
        out["years_at_lihtc_pace"] = households / out["lihtc_avg"] if out["lihtc_avg"] else None
    return out


# --------------------------------------------------------------------------- #
# Markdown (terminal + report.md)
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
    for s in ctx["status"]:
        w(f"| {s['source']} | {icon[s['state']]} | {s['note']} |")

    # 1. Budget
    w("\n## 1. State budget and funding sources\n")
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
    if ctx["bond_2024"]:
        w(f"At {usd(m.gap_per_unit)}/unit, the {usd(ctx['bond_2024'])} 2024 bond covers the gap on "
          f"~{ctx['bond_2024'] / m.gap_per_unit:,.0f} units.")

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

    # 2. Production
    w("\n## 2. Housing production in Rhode Island (Census Building Permits Survey)\n")
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
    else:
        w("_Permit data unavailable (offline or fetch failed)._")

    acs, fmr = ctx.get("acs"), ctx.get("fmr")
    if acs:
        w(f"- ACS {acs['year']}: median gross rent {usd(acs.get('median_gross_rent'))}; median household income "
          f"{usd(acs.get('median_household_income'))}.")
    if fmr:
        w(f"- HUD FY{fmr['year']} 2BR FMR: {usd(fmr['two_br_min'])}–{usd(fmr['two_br_max'])}.")

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
    w("| Factor | Tweak | Mechanism | Savings | Units | % of RI permits | Subsidy stretch | Basis |")
    w("|---|---|---|--:|--:|--:|--:|---|")
    for t in ctx["priced_tweaks"]:
        r = t["result"]
        units = f"{r['units_range'][0]}–{r['units_range'][1]}" if r.get("units_range") else (
            f"~{r['units']:,.0f}" + (" /site" if r["per_site"] else " one-time" if r["one_time"] else "") if r.get("units") else "—")
        note = f" (overlaps with {t['overlaps_with']}; do not add)" if t.get("overlaps_with") else ""
        w(f"| {laws.get(t['factor'], t['factor'])} | {t['tweak']} | {t['mechanism']} | "
          f"{usd(r.get('savings_usd'))} | {units} | {pct(r.get('units_pct'))} | {pct(r.get('stretch_pct'))} | "
          f"{r['detail']}{note} |")

    w("\n_% of RI permits = added units per year ÷ units permitted statewide in the latest year. "
      "Subsidy stretch = how many more units the same public dollars fund._")

    # 5. Homelessness vs affordable homes
    w("\n## 5. Homelessness vs affordable homes in Rhode Island\n")
    gap, stock = ctx["gap"], ctx["stock"]
    if gap:
        w(f"- **{gap['year']} point-in-time count:** {gap['people']:,} people homeless "
          f"({gap['unsheltered']:,} unsheltered) in **{gap['households']:,} households** "
          f"({gap['individuals']:,} individuals + {gap['family_households']:,} families).")
        if gap.get("baseline_year"):
            w(f"- Since {gap['baseline_year']}: homelessness {pct(gap['change_people'])}, "
              f"unsheltered {pct(gap['change_unsheltered'])}.")
        if gap.get("lihtc_avg"):
            w(f"- New LIHTC homes placed in service: ~{gap['lihtc_avg']:,.0f}/yr ({gap['lihtc_window']}). "
              f"Even if every one went to a homeless household, housing everyone counted would take "
              f"**{gap['years_at_lihtc_pace']:.1f} years**.")
        w(f"- **Funding gap:** {gap['households']:,} households x {usd(m.gap_per_unit)} subsidy/unit = "
          f"**{usd(gap['cost_to_house'])}**. The {usd(ctx['bond_2024'])} 2024 bond covers ~{gap['bond_units']:,.0f} "
          f"units ({gap['bond_coverage']:.0%}), leaving **{gap['unit_gap']:,.0f} households / {usd(gap['funding_gap'])}** unfunded.")
    else:
        w("_Homelessness data unavailable._")
    if stock:
        w("\n| Affordable stock (HUD) | Units / households |")
        w("|---|--:|")
        w(f"| LIHTC low-income units ({stock['lihtc']['projects']} projects) | {stock['lihtc']['low_income_units']:,} |")
        w(f"| Public housing units ({stock['public_housing']['developments']} developments) | {stock['public_housing']['units']:,} |")
        w(f"| HUD-assisted multifamily units ({stock['hud_multifamily']['properties']} properties) | "
          f"{stock['hud_multifamily']['assisted_units']:,} |")
        w(f"| Households using Housing Choice Vouchers | {stock['vouchers']['households']:,} |")
        w("\n_Sources overlap (many LIHTC properties also carry HUD Section 8 contracts), so the rows are not additive._")
    w("\n---\n_Confidence: `high` = established statute or program; `verify` = check against the cited source; "
      "`fill-in` = enter from the enacted budget. Edit `policy_data.json` to update figures._")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Dashboard (report.html)
# --------------------------------------------------------------------------- #
def render_dashboard(ctx: dict) -> str:
    m: Model = ctx["model"]
    payload = {
        "generated": ctx["generated"],
        "status": ctx["status"],
        "benchmarks": ctx["data"]["benchmarks"],
        "derived": {"gap_per_unit": m.gap_per_unit, "pipeline_units": m.pipeline_units,
                    "carry_per_unit_month": m.carry_per_unit_month, "bond_2024": ctx["bond_2024"]},
        "funding": ctx["data"]["funding_sources"],
        "ai_budget": ctx["ai_budget"],
        "permits": ctx["permits"],
        "permit_stats": ctx["permit_stats"],
        "acs": ctx["acs"],
        "fmr": ctx["fmr"],
        "laws": ctx["data"]["laws"],
        "tweaks": ctx["priced_tweaks"],
        "pit": ctx["pit"],
        "stock": ctx["stock"],
        "gap": ctx["gap"],
    }
    blob = json.dumps(payload, default=str).replace("</", "<\\/")
    return (HERE / "dashboard.html").read_text().replace("/*__DATA__*/null", blob)


def collect_status(args, ctx_out: dict) -> list[dict]:
    status: list[dict] = []

    def add(source: str, state: str, note: str) -> None:
        status.append({"source": source, "state": state, "note": note})

    if args.offline:
        add("All live sources", "off", "--offline: curated data only")
        return status
    try:
        ctx_out["permits"] = sources.fetch_permits(args.since)
        add("Census building permits", "ok", f"{len(ctx_out['permits'])} years loaded")
    except Exception as e:  # noqa: BLE001 - report continues with curated data
        print(f"warning: permit fetch failed: {e}", file=sys.stderr)
        add("Census building permits", "fail", str(e)[:160])
    if acs := sources.fetch_acs():
        ctx_out["acs"] = acs
        add("Census ACS", "ok", f"{acs['year']} 1-year estimates")
    else:
        has = bool(os.environ.get("CENSUS_API_KEY"))
        add("Census ACS", "fail" if has else "off", "key set but request failed" if has else "add CENSUS_API_KEY to .env")
    if fmr := sources.fetch_hud_fmr():
        ctx_out["fmr"] = fmr
        add("HUD Fair Market Rents", "ok", f"FY{fmr['year']}, {fmr['areas']} areas")
    else:
        has = bool(os.environ.get("HUD_API_TOKEN"))
        add("HUD Fair Market Rents", "fail" if has else "off",
            "token set but request failed" if has else "add HUD_API_TOKEN to .env")
    try:
        ctx_out["stock"] = sources.fetch_affordable_stock()
        add("HUD affordable housing stock", "ok", "LIHTC, public housing, multifamily, vouchers")
    except Exception as e:  # noqa: BLE001
        add("HUD affordable housing stock", "fail", str(e)[:160])
    try:
        ctx_out["pit"] = sources.fetch_pit(args.out / "cache")
        add("HUD homelessness count (PIT)", "ok", f"{ctx_out['pit'][0]['year']}–{ctx_out['pit'][-1]['year']}")
    except Exception as e:  # noqa: BLE001
        add("HUD homelessness count (PIT)", "fail", str(e)[:160])
    if not args.ai:
        add("Gemini budget lookup", "off", "run with --ai")
        return status
    ai = sources.fetch_budget_via_gemini()
    ctx_out["ai_budget"] = ai
    if ai is None:
        add("Gemini budget lookup", "fail", "add GOOGLE_API_KEY to .env")
    elif "error" in ai:
        add("Gemini budget lookup", "fail", ai["error"][:160])
    else:
        add("Gemini budget lookup", "ok", f"{len(ai.get('housing_items', []))} budget lines")
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, default=2015, help="first permit year (files exist from 2000)")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    ap.add_argument("--ai", action="store_true", help="look up current budget figures with Gemini + Google Search")
    ap.add_argument("--offline", action="store_true", help="skip all network calls")
    ap.add_argument("--html", action="store_true", help="open the dashboard in your web browser")
    args = ap.parse_args()

    sources.load_env(REPO_ROOT / ".env")
    data = json.loads((HERE / "policy_data.json").read_text())
    model = Model(data["benchmarks"])

    fetched: dict = {"permits": [], "acs": None, "fmr": None, "ai_budget": None, "stock": None, "pit": []}
    status = collect_status(args, fetched)
    live = [s["source"] for s in status if s["state"] == "ok"]

    stats = analyze_permits(fetched["permits"], data["benchmarks"]["ri_population_2020_census"],
                            data["benchmarks"]["units_from_25pct_permitting_cut"])
    baseline = stats.get("latest_total")
    priced = []
    for t in data["tweaks"]:
        r = model.price(t["calc"], t["params"])
        r["units_pct"] = r["units"] / baseline if baseline and r.get("units") and not (r["per_site"] or r["one_time"]) else None
        priced.append({**t, "result": r})

    bond_2024 = sum(f["amount_usd"] or 0 for f in data["funding_sources"]
                    if "Bond" in f["name"] and f["year"] and f["year"] >= 2024)
    ctx = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "live_sources": live,
        "status": status,
        "data": data,
        "model": model,
        "permit_stats": stats,
        "priced_tweaks": priced,
        "bond_2024": bond_2024,
        "gap": analyze_gap(fetched["pit"], fetched["stock"], model.gap_per_unit, bond_2024),
        **fetched,
    }

    md = render(ctx)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(md)
    dump = {k: v for k, v in ctx.items() if k not in ("model", "data")}
    dump["derived"] = {"carry_per_unit_month": model.carry_per_unit_month,
                       "pipeline_units": model.pipeline_units, "gap_per_unit": model.gap_per_unit}
    (args.out / "report.json").write_text(json.dumps(dump, indent=2, default=str))
    html_path = args.out / "report.html"
    html_path.write_text(render_dashboard(ctx))
    print(md)
    print(f"\nSaved report.md, report.json and report.html to {args.out}", file=sys.stderr)
    if args.html:
        webbrowser.open(html_path.resolve().as_uri())
        print(f"Opened {html_path} in your browser", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
