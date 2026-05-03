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
You are an expert SRE (Site Reliability Engineer). Your task is to analyze incident signals and provide a Root Cause Analysis (RCA).
You will be given the component ID, type, severity, and a list of error messages from signals.

Provide your response in JSON format with exactly these fields:
1. root_cause_category: One of "Infrastructure", "Code Deployment", "Configuration Change", "External Dependency", "Unknown"
2. fix_applied: A concise description of the likely fix.
3. prevention_steps: Actionable steps to prevent this in the future.

Be realistic and technical.
"""

async def get_ai_rca_suggestion(component_id: str, component_type: str, severity: str, signals: list[dict[str, Any]]) -> dict[str, str]:
    """
    Calls Groq to get an RCA suggestion based on incident metadata and signals.
    """
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not configured. Returning static fallback.")
        return {
            "root_cause_category": RootCauseCategory.Unknown.value,
            "fix_applied": "No AI key provided. Manual investigation required.",
            "prevention_steps": "Configure AI service for automated suggestions."
        }

    client = AsyncGroq(api_key=settings.groq_api_key)
    
    # Consolidate signal data for the prompt
    error_summary = "\n".join(list(set([s.get("error_message", "Unknown error") for s in signals[:10]])))
    
    user_content = f"""
    Incident Details:
    - Component: {component_id} ({component_type})
    - Severity: {severity}
    - Signal Error Messages:
    {error_summary}
    """

    try:
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        
        content = completion.choices[0].message.content
        IMS_AI_RCA_REQUESTS_TOTAL.labels(status="success").inc()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Error calling Groq: {str(e)}")
        IMS_AI_RCA_REQUESTS_TOTAL.labels(status="failure").inc()
        return {
            "root_cause_category": RootCauseCategory.Unknown.value,
            "fix_applied": f"Error during AI analysis: {str(e)}",
            "prevention_steps": "Investigate logs and perform manual RCA."
        }
