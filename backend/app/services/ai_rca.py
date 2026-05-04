import json
import logging
from typing import Any

from groq import AsyncGroq

from app.config import get_settings
from app.models.schemas import RootCauseCategory
from app.services.metrics import IMS_AI_RCA_REQUESTS_TOTAL

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """
You are a Staff Site Reliability Engineer (SRE). Your objective is to perform a Root Cause Analysis (RCA) on a production incident.
You will be provided with incident metadata (Component, Severity) and a high-velocity stream of error signals.

CRITICAL INSTRUCTIONS:
1. Identify the 'Direct Cause' (the immediate failure) and the 'Root Cause' (the underlying systemic issue).
2. Categorize the incident into exactly one of: "Infrastructure", "Code Deployment", "Configuration Change", "External Dependency", "Unknown".
3. Suggest a 'Fix Applied' that follows SRE best practices (e.g., progressive rollout, circuit breaking, horizontal scaling).
4. Provide 'Prevention Steps' aimed at improving the system's MTBF (Mean Time Between Failures) and observability.

RESPONSE FORMAT:
You MUST respond with a valid JSON object containing:
- root_cause_category: (string)
- fix_applied: (string)
- prevention_steps: (string)

Be concise, technical, and authoritative.
"""

async def get_ai_rca_suggestion(component_id: str, component_type: str, severity: str, signals: list[dict[str, Any]]) -> dict[str, str]:
    """
    Calls Groq (Llama 3.3) to generate a high-fidelity RCA suggestion.
    """
    if not settings.groq_api_key or "your_groq_api_key" in settings.groq_api_key:
        logger.warning("GROQ_API_KEY is missing or using placeholder. Returning fallback RCA.")
        return {
            "root_cause_category": RootCauseCategory.Unknown.value,
            "fix_applied": "Manual investigation required. AI key is not configured.",
            "prevention_steps": "Set a valid GROQ_API_KEY in the .env.example file to enable automated RCA."
        }

    client = AsyncGroq(api_key=settings.groq_api_key)
    
    # Extract unique error patterns to reduce token noise while keeping context
    error_patterns = []
    seen = set()
    for s in signals:
        msg = s.get("error_message", "Unknown")
        if msg not in seen:
            error_patterns.append(msg)
            seen.add(msg)
    
    user_content = f"""
    [INCIDENT CONTEXT]
    Component ID: {component_id}
    Component Type: {component_type}
    Severity Level: {severity}
    Signal Count: {len(signals)}
    
    [OBSERVED ERROR PATTERNS]
    {chr(10).join(error_patterns[:15])}
    """

    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.15,  # Low temperature for deterministic SRE analysis
            max_tokens=500,
        )
        
        IMS_AI_RCA_REQUESTS_TOTAL.labels(status="success").inc()
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        logger.error(f"Groq API Error: {str(e)}")
        IMS_AI_RCA_REQUESTS_TOTAL.labels(status="failure").inc()
        return {
            "root_cause_category": RootCauseCategory.Unknown.value,
            "fix_applied": f"AI service error: {str(e)}",
            "prevention_steps": "Verify Groq API status and check your API key quota."
        }

