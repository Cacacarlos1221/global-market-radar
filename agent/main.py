"""CLI: plan -> flow (offline/LLM) -> human review -> explicit publish."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .flow import run_flow
from .model_client import ChatCompletionsClient
from .orchestrator import ROOT, build_analysis, plan, publish_reviewed, write_preview

def main():
    parser = argparse.ArgumentParser(description="Experimental Stage-2 Agent, never scheduled on main")
    parser.add_argument("action", choices=("plan", "flow", "generate", "publish"))
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    parser.add_argument("--evidence", type=Path, help="Explicitly reviewed original reporting / filings")
    parser.add_argument("--offline", action="store_true", help="For flow: no LLM, research queue and HTML only")
    parser.add_argument("--reviewed", action="store_true", help="For publish: confirm reviewed draft")
    parser.add_argument("--render", action="store_true", help="On publish: regenerate existing site locally")
    args = parser.parse_args()
    if datetime.strptime(args.date, "%Y-%m-%d").date().isoformat() != args.date:
        parser.error("Use an ISO YYYY-MM-DD date")
    if (args.reviewed or args.render) and args.action != "publish":
        parser.error("--reviewed and --render are only for publish")
    if args.offline and args.action != "flow":
        parser.error("--offline is only for flow")
    if args.action == "plan":
        out = plan(ROOT, args.date, args.evidence)
    elif args.action == "flow":
        out = run_flow(ROOT, args.date,
                       None if args.offline else ChatCompletionsClient(), args.evidence)
    elif args.action == "generate":
        doc = build_analysis(ROOT, args.date, ChatCompletionsClient(), args.evidence)
        out = {"preview": str(write_preview(ROOT, args.date, doc)),
               "news_count": len(doc["news_digest"]["items"]),
               "warning": "generate is a legacy single-pass draft; prefer flow with critic"}
    else:
        out = {"published": str(publish_reviewed(ROOT, args.date, args.evidence,
                                                reviewed=args.reviewed, render=args.render))}
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
