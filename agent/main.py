"""CLI for experimental market-research / LLM-analysis pipeline."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .flow import run_flow
from .model_client import ChatCompletionsClient, model_configuration
from .orchestrator import ROOT, build_analysis, plan, publish_reviewed, write_preview
from .research_runner import run_research
from .official_runner import run_official_research

def main():
    parser = argparse.ArgumentParser(description="Experimental Agent; does not deploy to main")
    parser.add_argument("action", choices=("doctor", "research", "research-official", "smoke-model", "plan",
                                          "flow", "generate", "publish"))
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    parser.add_argument("--evidence", type=Path, help="Human-reviewed evidence JSON, never raw RSS")
    parser.add_argument("--offline", action="store_true", help="Flow: render without an LLM key")
    parser.add_argument("--research-model", action="store_true", help="Research: LLM corroboration of GDELT candidates")
    parser.add_argument("--max-articles", type=int, default=8, help="Research --web article budget")
    parser.add_argument("--reviewed", action="store_true", help="Publish: human confirms approval")
    parser.add_argument("--render", action="store_true", help="Publish: regenerate HTML locally")
    args = parser.parse_args()
    if datetime.strptime(args.date, "%Y-%m-%d").date().isoformat() != args.date:
        parser.error("Use YYYY-MM-DD")
    if (args.reviewed or args.render) and args.action != "publish":
        parser.error("--reviewed and --render are only for publish")
    if args.offline and args.action != "flow":
        parser.error("--offline is only for flow")
    if (args.research_model or args.max_articles != 8) and args.action != "research":
        parser.error("--research-model and --max-articles are only for research")
    if args.action == "doctor":
        out = {"python": sys.version.split()[0], "project_root": str(ROOT),
               "model": model_configuration(),
               "key_needed_for": "smoke-model, LLM flow and --research-model; not for keyless research/offline flow"}
    elif args.action == "research":
        out = run_research(ROOT, args.date, provider="web",
                           client=ChatCompletionsClient() if args.research_model else None,
                           max_articles=args.max_articles)
    elif args.action == "research-official":
        out = run_official_research(ROOT, args.date)
    elif args.action == "smoke-model":
        result = ChatCompletionsClient().generate_json(
            'Return exactly one JSON object {"ok":true}. No prose or Markdown.',
            'Reply with {"ok":true} only.')
        out = {"model_api_reachable": result.get("ok") is True, "response": result}
    elif args.action == "plan":
        out = plan(ROOT, args.date, args.evidence)
    elif args.action == "flow":
        out = run_flow(ROOT, args.date,
                       None if args.offline else ChatCompletionsClient(), args.evidence)
    elif args.action == "generate":
        doc = build_analysis(ROOT, args.date, ChatCompletionsClient(), args.evidence)
        out = {"preview": str(write_preview(ROOT, args.date, doc)),
               "news_count": len(doc["news_digest"]["items"]),
               "warning": "Legacy single-pass: prefer flow with critic"}
    else:
        out = {"published": str(publish_reviewed(ROOT, args.date, args.evidence,
                                                reviewed=args.reviewed, render=args.render))}
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
