"""Live data fetchers. Standard library only.

Keyless:   Census Building Permits Survey (annual state files)
Optional:  CENSUS_API_KEY  -> ACS housing/rent/cost-burden
           HUD_API_TOKEN   -> HUD Fair Market Rents
           GOOGLE_API_KEY  -> Gemini with Google Search grounding (budget lookup)
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

RI_FIPS = "44"
TIMEOUT = 20


def _ssl_context() -> ssl.SSLContext:
    # python.org macOS builds ship without a CA bundle; fall back to certifi or the system bundle.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs() and Path("/etc/ssl/cert.pem").exists():
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


SSL_CTX = _ssl_context()


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines from the repo .env without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ri-housing-report/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "ri-housing-report/1.0", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as resp:
        return json.loads(resp.read())


# --------------------------------------------------------------------------- #
# Census Building Permits Survey
# --------------------------------------------------------------------------- #
BPS_URL = "https://www2.census.gov/econ/bps/State/st{year}a.txt"


def fetch_permits(first_year: int, last_year: int | None = None) -> list[dict]:
    """Units authorized by building permits in RI, per year (reported + imputed)."""
    last_year = last_year or date.today().year
    rows = []
    for year in range(first_year, last_year + 1):
        try:
            text = _get(BPS_URL.format(year=year))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue  # year not published yet
            raise
        for line in text.splitlines():
            cols = line.split(",")
            if len(cols) > 17 and cols[1] == RI_FIPS:
                u1, u2, u34, u5 = (int(cols[i]) for i in (6, 9, 12, 15))
                rows.append(
                    {
                        "year": year,
                        "units_1": u1,
                        "units_2": u2,
                        "units_3_4": u34,
                        "units_5_plus": u5,
                        "total_units": u1 + u2 + u34 + u5,
                        "value_usd": sum(int(cols[i]) for i in (7, 10, 13, 16)) * 1000,
                    }
                )
    return rows


# --------------------------------------------------------------------------- #
# Census ACS (needs free key: https://api.census.gov/data/key_signup.html)
# --------------------------------------------------------------------------- #
ACS_VARS = {
    "B25001_001E": "housing_units",
    "B25002_003E": "vacant_units",
    "B25064_001E": "median_gross_rent",
    "B19013_001E": "median_household_income",
    "B25070_001E": "renter_households_computed",
    "B25070_007E": "rent_30_35pct",
    "B25070_008E": "rent_35_40pct",
    "B25070_009E": "rent_40_50pct",
    "B25070_010E": "rent_50pct_plus",
}


def fetch_acs() -> dict | None:
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        return None
    get = ",".join(ACS_VARS)
    for year in range(date.today().year - 1, date.today().year - 5, -1):
        url = f"https://api.census.gov/data/{year}/acs/acs1?get={get}&for=state:{RI_FIPS}&key={key}"
        try:
            header, values = json.loads(_get(url))[:2]
        except (urllib.error.HTTPError, json.JSONDecodeError, ValueError):
            continue
        out = {ACS_VARS[h]: int(v) for h, v in zip(header, values) if h in ACS_VARS and v not in (None, "")}
        out["year"] = year
        burdened = sum(out.get(k, 0) for k in ("rent_30_35pct", "rent_35_40pct", "rent_40_50pct", "rent_50pct_plus"))
        if out.get("renter_households_computed"):
            out["rent_burdened_share"] = burdened / out["renter_households_computed"]
            out["severely_burdened_share"] = out["rent_50pct_plus"] / out["renter_households_computed"]
        return out
    return None


# --------------------------------------------------------------------------- #
# HUD USER API (token: https://www.huduser.gov/hudapi/public/register)
# --------------------------------------------------------------------------- #
def fetch_hud_fmr() -> dict | None:
    token = os.environ.get("HUD_API_TOKEN")
    if not token:
        return None
    try:
        data = json.loads(
            _get("https://www.huduser.gov/hudapi/public/fmr/statedata/RI", {"Authorization": f"Bearer {token}"})
        )["data"]
    except (urllib.error.HTTPError, KeyError, json.JSONDecodeError):
        return None
    areas = (data.get("metroareas") or []) + (data.get("counties") or [])
    two_br = sorted(a["Two-Bedroom"] for a in areas if a.get("Two-Bedroom"))
    if not two_br:
        return None
    return {
        "year": data.get("year"),
        "areas": len(areas),
        "two_br_min": two_br[0],
        "two_br_median": two_br[len(two_br) // 2],
        "two_br_max": two_br[-1],
    }


# --------------------------------------------------------------------------- #
# Gemini + Google Search grounding: budget figures that have no public API
# --------------------------------------------------------------------------- #
BUDGET_PROMPT = """You are a Rhode Island state budget analyst. Using Google Search, find the most
recent ENACTED Rhode Island state budget (and the Governor's proposal for the next fiscal year if
published) and report housing-related figures. Return ONLY a JSON object, no prose:
{
  "fiscal_year": "FY20XX",
  "total_state_budget_usd": number|null,
  "housing_items": [
    {"name": str, "amount_usd": number, "fund_type": "general revenue|federal|restricted|bond|other",
     "description": str, "source_url": str}
  ],
  "notes": str
}
Include the Department of Housing appropriation, Housing Production Fund, homelessness programs,
housing bond proceeds, and any conveyance-tax revenue dedicated to housing. Use only figures you
found in sources; never estimate."""


def fetch_budget_via_gemini() -> dict | None:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"contents": [{"parts": [{"text": BUDGET_PROMPT}]}], "tools": [{"google_search": {}}]}
    try:
        resp = _post_json(url, payload, {"x-goog-api-key": key.strip()})
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"error": "Gemini 429: Google Search grounding quota exhausted for this key. "
                             "Enable billing for the key's project in AI Studio, or retry after the quota resets."}
        return {"error": f"Gemini HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"}
    candidate = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"error": "Gemini returned no JSON", "raw": text[:500]}
    try:
        result = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"error": "Gemini returned malformed JSON", "raw": text[:500]}
    chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
    result["grounding_sources"] = [c["web"].get("uri") for c in chunks if c.get("web")]
    result["model"] = model
    return result
