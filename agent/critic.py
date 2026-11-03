"""Second-pass LLM critique, always followed by deterministic validation."""
import json
from pathlib import Path
from .validators import validate_generated
from .research import summarize_sources

CRITIC_PROMPT = (Path(__file__).with_name("prompts") / "critic.md")

def critique(client, analysis, snapshot, reviewed_sources, snapshot_sha):
    validate_generated(analysis, analysis["report_date"], reviewed_sources, snapshot_sha)
    context = {
        "report_date": analysis["report_date"],
        "run_at_utc": analysis["agent_meta"]["run_at_utc"],
        "price_facts": snapshot["quotes"],
        "reviewed_fact_notes": summarize_sources(reviewed_sources),
        "analysis_to_check": {
            key: analysis[key] for key in
            ("market_summary", "a_share_bias", "a_share_outlook", "a_share_sectors",
             "risks", "uncertainty", "news_digest")
        },
    }
    result = client.generate_json(CRITIC_PROMPT.read_text(encoding="utf-8"),
                                  json.dumps(context, ensure_ascii=False))
    if not isinstance(result.get("approved"), bool):
        raise ValueError("Critic must return boolean approved")
    findings = result.get("findings")
    if not isinstance(findings, list) or not all(isinstance(x, str) for x in findings):
        raise ValueError("Critic must return list of string findings")
    if result["approved"] is not True or findings:
        raise ValueError("Agent critic blocked the draft: " + "; ".join(findings or ["not approved"]))
    return {"approved": True, "findings": [], "review_method": "llm_critic_plus_deterministic_validation"}
