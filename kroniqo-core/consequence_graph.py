"""
kroniqo-core: Consequence Graph Engine
The heart of Kroniqo — tracks decisions, outcomes, and shapes agent behavior over time.
"""

import sqlite3
import json
import math
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).parent / "kroniqo.db"


def init_db():
    """Initialize the consequence graph database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS consequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            domain TEXT NOT NULL,
            task TEXT NOT NULL,
            confidence_expressed REAL,
            outcome TEXT CHECK(outcome IN ('correct', 'wrong', 'partial', 'pending')),
            magnitude TEXT CHECK(magnitude IN ('small', 'medium', 'large')),
            context TEXT,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_decision(domain: str, task: str, confidence: float, context: dict = None):
    """
    Log a decision before its outcome is known.
    Returns the decision ID to update later with the outcome.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO consequences (timestamp, domain, task, confidence_expressed, outcome, context)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        datetime.utcnow().isoformat(),
        domain,
        task,
        confidence,
        json.dumps(context or {})
    ))
    decision_id = c.lastrowid
    conn.commit()
    conn.close()
    return decision_id


def record_outcome(decision_id: int, outcome: str, magnitude: str = "medium", notes: str = ""):
    """
    Record what actually happened after a decision.
    outcome: 'correct' | 'wrong' | 'partial'
    magnitude: 'small' | 'medium' | 'large'
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE consequences
        SET outcome = ?, magnitude = ?, notes = ?
        WHERE id = ?
    """, (outcome, magnitude, notes, decision_id))
    conn.commit()
    conn.close()


def get_biography(domain: str = None) -> dict:
    """
    Build the agent's biography — the core of what shapes its behavior.
    Applies recency decay: recent events weigh more than old ones.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    query = """
        SELECT domain, outcome, magnitude, confidence_expressed, timestamp
        FROM consequences
        WHERE outcome != 'pending'
    """
    params = []
    if domain:
        query += " AND domain = ?"
        params.append(domain)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()

    if not rows:
        return {"age": 0, "domains": {}, "summary": "No experience yet. I am new."}

    now = datetime.utcnow()
    domain_stats = {}

    for row in rows:
        d, outcome, magnitude, confidence, timestamp_str = row
        ts = datetime.fromisoformat(timestamp_str)
        days_ago = (now - ts).total_seconds() / 86400

        # Recency decay
        decay_weight = math.exp(-0.03 * days_ago)
        magnitude_weight = {"small": 0.5, "medium": 1.0, "large": 2.0}.get(magnitude, 1.0)
        event_weight = decay_weight * magnitude_weight

        if d not in domain_stats:
            domain_stats[d] = {
                "total": 0, "correct": 0, "wrong": 0, "partial": 0,
                "weighted_correct": 0, "weighted_wrong": 0,
                "confidence_history": [], "recent_streak": []
            }

        domain_stats[d]["total"] += 1
        domain_stats[d][outcome] += 1
        domain_stats[d]["confidence_history"].append(confidence or 0.5)

        if outcome == "correct":
            domain_stats[d]["weighted_correct"] += event_weight
        elif outcome == "wrong":
            domain_stats[d]["weighted_wrong"] += event_weight

        domain_stats[d]["recent_streak"].append(outcome)

    profiles = {}
    for d, stats in domain_stats.items():
        total_weighted = stats["weighted_correct"] + stats["weighted_wrong"]
        weighted_accuracy = (
            stats["weighted_correct"] / total_weighted if total_weighted > 0 else 0.5
        )
        recent = stats["recent_streak"][-5:]
        recent_wrongs = recent.count("wrong")
        avg_confidence = sum(stats["confidence_history"]) / len(stats["confidence_history"])

        profiles[d] = {
            "total_decisions": stats["total"],
            "raw_accuracy": round(stats["correct"] / stats["total"], 3),
            "weighted_accuracy": round(weighted_accuracy, 3),
            "avg_confidence_expressed": round(avg_confidence, 3),
            "recent_form": recent,
            "recent_wrongs": recent_wrongs,
            "calibration": "overconfident" if avg_confidence > weighted_accuracy + 0.15 else
                           "underconfident" if avg_confidence < weighted_accuracy - 0.15 else
                           "calibrated"
        }

    total_decisions = sum(s["total"] for s in domain_stats.values())

    return {
        "age": total_decisions,
        "domains": profiles,
        "summary": _build_summary(profiles, total_decisions)
    }


def _build_summary(profiles: dict, total_decisions: int) -> str:
    if total_decisions == 0:
        return "No experience yet. I am new."

    lines = [f"I have made {total_decisions} consequential decisions across {len(profiles)} domain(s)."]

    for domain, p in profiles.items():
        acc = p["weighted_accuracy"]
        recent_wrongs = p["recent_wrongs"]
        calibration = p["calibration"]

        confidence_tone = (
            "I am strong here" if acc >= 0.75 else
            "I am developing here" if acc >= 0.55 else
            "I have struggled here"
        )

        streak_note = ""
        if recent_wrongs >= 3:
            streak_note = " Recent form is poor — I should be cautious."
        elif recent_wrongs == 0 and p["total_decisions"] >= 3:
            streak_note = " Recent form is strong."

        lines.append(
            f"In [{domain}]: weighted accuracy {acc:.0%}, {calibration}.{streak_note} {confidence_tone}."
        )

    return " ".join(lines)


def get_behavioral_modifier(domain: str) -> dict:
    """
    Returns behavioral modifiers injected into the agent's system prompt
    before it makes a decision. This is where aging shapes behavior.
    """
    bio = get_biography(domain)

    if domain not in bio["domains"]:
        return {
            "confidence_modifier": 0.0,
            "risk_posture": "neutral",
            "biography_note": "No prior experience in this domain. Proceeding openly.",
            "age": 0
        }

    p = bio["domains"][domain]
    acc = p["weighted_accuracy"]
    recent_wrongs = p["recent_wrongs"]

    confidence_modifier = (acc - 0.5) * 0.6

    risk_posture = (
        "conservative" if recent_wrongs >= 3 else
        "bold" if recent_wrongs == 0 and p["total_decisions"] >= 5 else
        "neutral"
    )

    return {
        "confidence_modifier": round(confidence_modifier, 3),
        "risk_posture": risk_posture,
        "biography_note": p,
        "age": bio["age"]
    }


init_db()
