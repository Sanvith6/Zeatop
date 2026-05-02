"""
Severity Auto-Classification — Rule-based severity validation and upgrade.

WHY THIS EXISTS:
Upstream signal producers (monitoring agents, health checkers) may not always
assign the correct severity. A cache miss might be reported as P0 by an
overeager alert rule, or a database outage might arrive as P2 because the
agent doesn't know the component's blast radius.

This classifier acts as a safety net:
  1. Maps each component_type to its baseline severity (based on blast radius)
  2. Validates the incoming severity against the baseline
  3. UPGRADES severity if the signal underestimates criticality
  4. NEVER DOWNGRADES — the producer may have context we don't

This is a rule-based approach. In production at scale, this would be replaced
with an ML model trained on historical incident data, but rule-based is the
right starting point for deterministic, auditable classification.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Component-type to baseline severity mapping.
#
# WHY these mappings:
#   P0: rdbms, mcp — Primary databases and control planes are single points
#       of failure. Their outage typically causes user-facing impact immediately.
#   P1: api, queue — Service-affecting but often have retries or fallbacks.
#       Users may experience degraded latency rather than complete outage.
#   P2: cache, nosql — Typically have automatic fallback to origin. Impact is
#       performance degradation, not data loss or complete service failure.
# ---------------------------------------------------------------------------

COMPONENT_BASELINE_SEVERITY: dict[str, str] = {
    "rdbms": "P0",
    "mcp": "P0",
    "api": "P1",
    "queue": "P1",
    "cache": "P2",
    "nosql": "P2",
}

SEVERITY_RANK: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def classify_severity(component_type: str, declared_severity: str) -> str:
    """
    Validate and potentially upgrade the declared severity.

    Returns the effective severity (may be higher priority than declared).
    Never downgrades — the producer may have additional context.
    """
    baseline = COMPONENT_BASELINE_SEVERITY.get(component_type)
    if baseline is None:
        # Unknown component type — trust the producer's assessment
        return declared_severity

    declared_rank = SEVERITY_RANK.get(declared_severity, 99)
    baseline_rank = SEVERITY_RANK.get(baseline, 99)

    if declared_rank > baseline_rank:
        # Signal was underclassified — upgrade to baseline
        logger.info(
            "Severity auto-upgraded: component_type=%s declared=%s → effective=%s "
            "(component baseline is %s)",
            component_type, declared_severity, baseline, baseline,
        )
        return baseline

    # Signal severity is already at or above baseline — trust the producer
    return declared_severity
