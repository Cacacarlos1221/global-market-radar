"""Morning close-pipeline smoke test using archived facts in an isolated directory."""
import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, time as clock
from pathlib import Path
from .close_review import ROOT, BJ, as_utc, check_release, data_path, render_close
from .close_facts_fallback import create_facts_fallback

def inspect(day, root=ROOT):
    datetime.strptime(day, "%Y-%m-%d")
    today_forecast = data_path(root, "forecasts", day)
    status = {"preflight_date": day, "today_forecast_exists": today_forecast.exists()}
    if not today_forecast.exists():
        status["error"] = "today's forecast not frozen at preflight"
        return status
    forecast = json.loads(today_forecast.read_text(encoding="utf-8"))
    freeze = forecast.get("frozen_at_utc")
    if not freeze:
        status["error"] = "today's forecast missing freeze timestamp"
        return status
    local = as_utc(freeze).astimezone(BJ)
    if local.date().isoformat() != day or local.time() >= clock(9, 30):
        status["error"] = "forecast freeze occurred outside valid market preopen window"
        return status
    status["frozen_at_utc"] = freeze
    snapshots = sorted((root / "data/close").glob("*/*/*.json"))
    prior = [p for p in snapshots if p.stem < day]
    if not prior:
        status["error"] = "no archived verified close snapshot for isolated simulation"
        return status
    reference = prior[-1]
    status["test_reference_date"] = reference.stem
    original = reference.read_bytes()
    with tempfile.TemporaryDirectory(prefix="gmr-close-preflight-") as temp:
        scratch = Path(temp)
        raw = data_path(scratch, "close", reference.stem)
        raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reference, raw)
        revision = data_path(root, "close_revisions", reference.stem)
        if revision.exists():
            target = data_path(scratch, "close_revisions", reference.stem)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(revision, target)
        fallback = create_facts_fallback(reference.stem, scratch)
        if fallback != "facts_fallback_created":
            status["error"] = "facts-only simulation failed: " + fallback
            return status
        render_close(scratch)
        verify = check_release(reference.stem, scratch)
        if not (verify.get("published") and not verify.get("has_independent_research")
                and verify.get("status") == "DEGRADED"):
            status["error"] = "facts-only simulated HTML not correctly marked DEGRADED"
            status["facts_check"] = verify
            return status
        status["facts_only_smoke"] = "DEGRADED_published"
        status["facts_only_html_bytes"] = (scratch / "reports/close/index.html").stat().st_size
        authored = data_path(root, "close_analysis", reference.stem)
        if authored.exists():
            dest = data_path(scratch, "close_analysis", reference.stem)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(authored, dest)
            render_close(scratch)
            upgrade = check_release(reference.stem, scratch)
            if not (upgrade.get("published") and upgrade.get("has_independent_research")):
                status["error"] = "independent research did not replace fallback in simulation"
                status["upgrade_check"] = upgrade
                return status
            status["independent_research_upgrade"] = upgrade.get("status")
            # A malformed later handoff must not erase a previously verified facts page.
            dest.write_text('{"report_date":"' + reference.stem + '","summary":""}', encoding="utf-8")
            render_close(scratch)
            invalid = check_release(reference.stem, scratch)
            if not (invalid.get("published") and invalid.get("status") == "DEGRADED"
                    and invalid.get("analysis_mode") == "facts_only_fallback"):
                status["error"] = "malformed later research displaced the verified facts page"
                status["invalid_research_check"] = invalid
                return status
            status["invalid_research_recovery"] = "DEGRADED_facts_restored"
        else:
            status["independent_research_upgrade"] = "not_tested_no_prior_research"
        if raw.read_bytes() != original:
            status["error"] = "original close data changed in smoke test"
            return status
        status["reference_sha256"] = hashlib.sha256(original).hexdigest()
    status["preflight_ok"] = True
    status["note"] = "Real historic data only copied into a temporary root; original repository files unchanged."
    return status

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="Asia/Shanghai market date; defaults to local today")
    a = p.parse_args()
    day = a.date or datetime.now(BJ).date().isoformat()
    result = inspect(day)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("preflight_ok"):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
