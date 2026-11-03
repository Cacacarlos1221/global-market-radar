"""CLI: plan -> generate preview -> human review -> explicit publish."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .model_client import ChatCompletionsClient
from .orchestrator import ROOT, build_analysis, plan, publish_reviewed, write_preview

def main():
    parser = argparse.ArgumentParser(description="Experimental market analysis agent (main is untouched)")
    parser.add_argument("action", choices=("plan", "generate", "publish"))
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    parser.add_argument("--evidence", type=Path, help="Manually reviewed evidence JSON; no automatic fact checking yet")
    parser.add_argument("--reviewed", action="store_true", help="Confirm preview was reviewed before publish")
    parser.add_argument("--render", action="store_true", help="On publish, regenerate local HTML using existing renderer")
    args = parser.parse_args()
    if datetime.strptime(args.date, "%Y-%m-%d").date().isoformat() != args.date:
        parser.error("Use ISO YYYY-MM-DD report date")
    if args.action != "publish" and (args.reviewed or args.render):
        parser.error("--reviewed and --render are only valid for publish")
    if args.action == "plan":
        out = plan(ROOT, args.date, args.evidence)
    elif args.action == "generate":
        doc = build_analysis(ROOT, args.date, ChatCompletionsClient(), args.evidence)
        out = {"preview": str(write_preview(ROOT, args.date, doc)),
               "news_count": len(doc["news_digest"]["items"])}
    else:
        out = {"published": str(publish_reviewed(ROOT, args.date, args.evidence,
                                                reviewed=args.reviewed, render=args.render))}
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
