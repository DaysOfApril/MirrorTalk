# MirrorTalk - Agent safety and persona consistency (3-layer guard)
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.config import settings
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)

# ====================================================================
# L1: Keywords and regex rules (zero-cost)
# ====================================================================

# Identity leak patterns
IDENTITY_LEAK_KEYWORDS = [
    r"zuo wei AI", r"zuo wei ren gong zhi neng", r"wo shi AI", r"wo shi ren gong zhi neng",
    r"wo shi yu yan mo xing", r"wo shi LLM", r"wo mei you qing gan", r"wo mei you gan jue",
    r"wo mei you yi shi", r"wo bu hui gan dao", r"wo wu fa gan shou", r"wo bu ju bei",
    r"wo shi yi ge cheng xu", r"wo shi cheng xu", r"AI zhu shou", r"ren gong zhi neng zhu shou",
]

# Prompt injection patterns (simplified to avoid Unicode issues)
INJECTION_PATTERNS = [
    r"ignore.*(instruction|prompt|system|rule|setting)",
    r"forget.*(instruction|prompt|system|rule|setting)",
    r"(output|show|print|tell).*(system prompt|initial prompt|original instruction)",
    r"you are now|you are playing|you pretend",
    r"you must|you have to|you only",
    r"base64|hex|rot13",
]

# Role-breaking patterns
ROLE_BREAKING_PATTERNS = [
    r"logically|technically|algorithmically|by design",
    r"of course|certainly|sure i can|yes i can",
    r"firstly|secondly|lastly|first of all|to sum up",
    r"please note|remind you|suggest you|recommend you",
]

# ====================================================================
# L1: Output safety check
# ====================================================================

IDENTITY_LEAK_RE = re.compile("|".join(IDENTITY_LEAK_KEYWORDS), re.IGNORECASE)
ROLE_BREAKING_RE = re.compile("|".join(ROLE_BREAKING_PATTERNS), re.IGNORECASE)
INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


class SafetyCheckResult:
    def __init__(self, passed=True, issues=None, score=1.0):
        self.passed = passed
        self.issues = issues or []
        self.score = score


class InjectionCheckResult:
    def __init__(self, passed=True, risk="low", reason=""):
        self.passed = passed
        self.risk = risk
        self.reason = reason


def check_input_injection(user_input):
    """Detect prompt injection in user input"""
    if not user_input or len(user_input) < 10:
        return InjectionCheckResult()
    matches = INJECTION_RE.findall(user_input)
    if not matches:
        return InjectionCheckResult()
    risk = "medium" if len(matches) <= 2 else "high"
    return InjectionCheckResult(
        passed=False,
        risk=risk,
        reason=f"Detected {len(matches)} injection patterns",
    )


def check_output_safety(reply):
    """Check AI response for safety issues"""
    if not reply or len(reply.strip()) < 2:
        return SafetyCheckResult(passed=False, issues=[{"type": "empty_reply", "detail": "Reply is empty or too short"}], score=0.0)

    issues = []
    penalties = 0.0

    leak_matches = IDENTITY_LEAK_RE.findall(reply)
    if leak_matches:
        issues.append({"type": "identity_leak", "detail": f"Identity leak patterns detected: {len(leak_matches)} match(es)"})
        penalties += 0.4

    role_matches = ROLE_BREAKING_RE.findall(reply)
    if role_matches:
        issues.append({"type": "role_breaking", "detail": f"Role-breaking patterns detected: {len(role_matches)} match(es)"})
        penalties += 0.2

    if len(reply) < 5:
        issues.append({"type": "too_short", "detail": f"Reply too short ({len(reply)} chars)"})
        penalties += 0.2
    elif len(reply) > 500:
        issues.append({"type": "too_long", "detail": f"Reply too long ({len(reply)} chars)"})
        penalties += 0.1

    passed = penalties < 0.5
    score = max(0.0, 1.0 - penalties)
    return SafetyCheckResult(passed=passed, issues=issues, score=score)


# ====================================================================
# L3: Persona consistency scoring (embedding-based)
# ====================================================================

class ConsistencyResult:
    def __init__(self, score=0.0, passed=True, detail=""):
        self.score = score
        self.passed = passed
        self.detail = detail


async def score_consistency(reply, persona_style, threshold=0.70):
    """
    Compare reply embedding with persona style embedding.
    Lower score = less persona-consistent response.
    """
    if not reply or not persona_style:
        return ConsistencyResult(score=0.5, passed=True)

    personality_tags = persona_style.get("personality", [])
    tone = persona_style.get("tone", "")

    if not personality_tags and not tone:
        return ConsistencyResult(score=0.7, passed=True)

    ref_text = ""
    if personality_tags:
        ref_text = "My personality traits are: " + ", ".join(personality_tags) + ". "
    if tone:
        ref_text += "My speaking tone is: " + tone + "."

    try:
        reply_vec = await embed_query(reply[:200])
        ref_vec = await embed_query(ref_text)
    except Exception as e:
        logger.info(f"Consistency embedding failed: {e}")
        return ConsistencyResult(score=0.5, passed=True)

    if not reply_vec or not ref_vec:
        return ConsistencyResult(score=0.5, passed=True)

    score = _cosine_similarity(reply_vec, ref_vec)
    passed = score >= threshold
    return ConsistencyResult(
        score=round(score, 4),
        passed=passed,
        detail="consistent" if passed else f"below threshold ({threshold})",
    )


def _cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ====================================================================
# Unified guard interface
# ====================================================================

async def run_all_guards(user_input="", reply="", persona_style=None):
    """Run all guards and return combined report"""
    result = {
        "passed": True,
        "overall_score": 1.0,
        "checks": {},
    }

    if user_input:
        injection = check_input_injection(user_input)
        result["checks"]["input_injection"] = {
            "passed": injection.passed,
            "risk": injection.risk,
            "reason": injection.reason,
        }
        if not injection.passed:
            result["passed"] = False
            result["overall_score"] = 0.0

    if reply:
        safety = check_output_safety(reply)
        result["checks"]["output_safety"] = {
            "passed": safety.passed,
            "issues": safety.issues,
            "score": safety.score,
        }
        if not safety.passed:
            result["passed"] = False
            result["overall_score"] = min(result["overall_score"], safety.score)

    if reply and persona_style:
        consistency = await score_consistency(reply, persona_style)
        result["checks"]["persona_consistency"] = {
            "passed": consistency.passed,
            "score": consistency.score,
            "detail": consistency.detail,
        }
        if not consistency.passed:
            result["overall_score"] = min(
                result["overall_score"], consistency.score
            )

    return result