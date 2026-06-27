"""
Atlas ESG Score engine (v2) — performance, completeness and data-trust scoring
that a bank can actually underwrite against.

Three distinct, transparent numbers:
  1. performance_score   — how sustainable the borrower actually is (the headline).
  2. completeness_score  — how much of the interview has been answered.
  3. data_trust_score    — interpretation confidence + plausibility/consistency checks.

Design principles (deliberate, for auditability):
  * Every sub-score is computed ONLY from approved answers and explains itself.
  * Inputs are bound to **canonical metric codes** (not question IDs), so the score
    is stable even when the interview questions are AI-generated/tailored per company.
  * All weights, curves, benchmarks and thresholds come from the runtime config
    store (`config_service`, namespaces `scoring.*`) — nothing is hardcoded.
  * Missing inputs are OMITTED and the remaining weights renormalize.
  * Sector-relative scoring uses a sourced, labelled benchmark; where none exists
    for a sector, NO benchmarked sub-score is produced (never a fabricated peer).
  * `allowed_pillars` scopes the entire result, so a bank granted a pillar subset
    never receives sub-scores or flags for pillars outside its grant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services import config_service

# ── Canonical metric codes the engine consumes (the stable binding) ─────────
M_ELEC = "ENERGY_ELEC_CONSUMPTION"
M_RENEWABLE = "ENERGY_RENEWABLE_PCT"
M_FUEL = "ENERGY_FUEL_CONSUMPTION"
M_GHG = "GHG_TOTAL_EMISSIONS"
M_RECYCLING = "WASTE_RECYCLING_RATE"
M_FTE = "WORKFORCE_TOTAL_FTE"
M_FEMALE = "WORKFORCE_GENDER_FEMALE_PCT"
M_MIN_WAGE = "WORKFORCE_MIN_WAGE_COMPLIANCE"
M_INCIDENTS = "SAFETY_RECORDABLE_INCIDENTS"

GOVERNANCE_METRICS = [
    ("GOV_CODE_OF_CONDUCT", "code_of_conduct", "Code of conduct / ethics policy"),
    ("GOV_ENVIRONMENTAL_POLICY", "env_policy", "Environmental policy / management system"),
    ("GOV_SUPPLIER_STANDARDS", "supplier_standards", "Supplier sustainability standards"),
    ("GOV_CLIMATE_RISK_ASSESSED", "climate_risk", "Climate-risk assessment"),
    ("GOV_SUSTAINABILITY_CERTIFICATIONS", "certifications", "Sustainability certifications"),
]


def _rubric() -> Dict[str, Any]:
    # Read-only hot path — peek returns live refs (we never mutate them).
    return config_service.peek("scoring.rubric")


def _benchmarks() -> Dict[str, Any]:
    return config_service.peek("scoring.sector_benchmarks")


def _interp(anchors: List[List[float]], x: float) -> float:
    """Piecewise-linear interpolation over [x, y] anchor points, clamped at ends."""
    pts = sorted(anchors, key=lambda p: p[0])
    if x <= pts[0][0]:
        return float(pts[0][1])
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y0)
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(pts[-1][1])


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def grade_for(score: Optional[float]) -> str:
    """A–E grade, matching the thresholds used across the frontend."""
    if score is None:
        return "—"
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "E"


class _SubScores:
    """Accumulates weighted sub-scores for one pillar, renormalizing over what exists."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, key: str, label: str, score: Optional[float], weight: float,
            detail: str, value: Any = None) -> None:
        self.items.append({
            "key": key, "label": label,
            "score": None if score is None else round(score),
            "weight": weight, "detail": detail, "value": value,
            "scored": score is not None,
        })

    def pillar_score(self) -> Optional[float]:
        scored = [i for i in self.items if i["scored"]]
        total_w = sum(i["weight"] for i in scored)
        if total_w <= 0:
            return None
        return sum(i["score"] * i["weight"] for i in scored) / total_w


def compute_score(
    workspace: Any,
    responses: List[Any],
    questions: List[Dict],
    allowed_pillars: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Pure scoring function. `workspace` needs .nace_sector and .turnover_range_eur;
    `responses` is a list of InterviewResponse; `questions` is the active interview
    set (default VSME catalogue or an approved blueprint). Inputs are read by the
    response's `interpreted_metric_code`, so question IDs may be anything.
    """
    rubric = _rubric()
    bench = _benchmarks()
    pillar_weights = rubric["pillar_weights"]

    # Approved values indexed by canonical metric code (the stable binding).
    by_metric = {r.interpreted_metric_code: r for r in responses
                 if r.status == "approved" and r.interpreted_metric_code}
    qpillar = {q["id"]: q["pillar"] for q in questions}
    allowed = set(allowed_pillars) if allowed_pillars else {"environmental", "social", "governance"}
    flags: List[Dict[str, str]] = []

    def flag(severity: str, code: str, message: str, pillar: str = "general") -> None:
        flags.append({"severity": severity, "code": code, "message": message, "pillar": pillar})

    def value_of(metric_code: str) -> Optional[float]:
        r = by_metric.get(metric_code)
        return r.interpreted_value if r else None

    def is_present(metric_code: str) -> Optional[bool]:
        r = by_metric.get(metric_code)
        if not r:
            return None
        if r.interpreted_value is not None:
            return r.interpreted_value >= 1
        return True  # text-presence questions: approval implies presence

    # ------------------------------------------------------------------ inputs
    elec = value_of(M_ELEC)
    renewable = value_of(M_RENEWABLE)
    fuel = value_of(M_FUEL)
    ghg = value_of(M_GHG)
    recycling = value_of(M_RECYCLING)
    fte = value_of(M_FTE)
    female_pct = value_of(M_FEMALE)
    min_wage = is_present(M_MIN_WAGE)
    incidents = value_of(M_INCIDENTS)

    sector_code = (workspace.nace_sector or "OTHER") if workspace else "OTHER"
    sector = bench["sectors"].get(sector_code, bench["sectors"]["OTHER"])
    turnover_mid = bench["turnover_midpoints_eur"].get(
        getattr(workspace, "turnover_range_eur", None) or "", None
    )

    # =============================================== ENVIRONMENTAL pillar ====
    env = _SubScores()
    ew = rubric["environmental_weights"]

    carbon_detail: Optional[Dict[str, Any]] = None
    sector_median = sector.get("carbon_intensity_tco2e_per_eur_m")
    if ghg is not None and ghg >= 0 and turnover_mid and sector_median:
        intensity = ghg * 1_000_000 / turnover_mid
        ratio = intensity / sector_median if sector_median else None
        curve = bench["_meta"]["carbon_intensity"]["scoring_curve"]["anchors"]
        ci_score = _interp(curve, ratio)
        env.add("carbon_intensity", "Carbon intensity vs sector", ci_score, ew["carbon_intensity"],
                f"{intensity:,.0f} tCO2e per €M turnover vs sector median {sector_median:,.0f} "
                f"({ratio:.1f}x peers)", value=round(intensity, 1))
        carbon_detail = {
            "intensity_tco2e_per_eur_m": round(intensity, 1),
            "sector_median": sector_median,
            "ratio_to_peers": round(ratio, 2),
            "sector_label": sector.get("label"),
            "confidence": sector.get("intensity_confidence"),
            "turnover_basis": "estimated from range midpoint",
        }
        if ratio >= rubric["carbon_outlier_ratio"]:
            flag("warn", "carbon_outlier",
                 f"Carbon intensity is {ratio:.0f}x the sector median — verify emissions and turnover before lending.",
                 pillar="environmental")
    else:
        reason = ("no sector benchmark" if not sector_median
                  else "GHG emissions not reported" if ghg is None
                  else "turnover not provided")
        env.add("carbon_intensity", "Carbon intensity vs sector", None, ew["carbon_intensity"],
                f"Not scored — {reason}.")
        if ghg is not None and not sector_median:
            flag("info", "no_sector_benchmark",
                 "Sector not classified — peer carbon comparison unavailable. Reclassify to a NACE section.",
                 pillar="environmental")

    if renewable is not None:
        env.add("renewable", "Renewable energy share", _clamp(renewable), ew["renewable"],
                f"{renewable:.0f}% renewable (EU grid avg ~45%)", value=renewable)
    else:
        env.add("renewable", "Renewable energy share", None, ew["renewable"], "Not reported.")

    if recycling is not None:
        env.add("recycling", "Waste recycling rate", _clamp(recycling), ew["recycling"],
                f"{recycling:.0f}% recycled/reused (EU municipal avg ~48%)", value=recycling)
    else:
        env.add("recycling", "Waste recycling rate", None, ew["recycling"], "Not reported.")

    # =============================================== SOCIAL pillar ===========
    soc = _SubScores()
    sw = rubric["social_weights"]

    if min_wage is not None:
        soc.add("min_wage", "Living/minimum wage compliance", 100.0 if min_wage else 0.0, sw["min_wage"],
                "All staff paid at/above minimum wage" if min_wage else "Below minimum wage reported",
                value=bool(min_wage))
        if not min_wage:
            flag("critical", "min_wage", "Borrower reports staff paid below minimum wage — social/regulatory risk.",
                 pillar="social")
    else:
        soc.add("min_wage", "Living/minimum wage compliance", None, sw["min_wage"], "Not reported.")

    if female_pct is not None:
        center = rubric["gender_balance_center"]
        slope = rubric["gender_balance_slope"]
        gscore = _clamp(100 - slope * abs(female_pct - center))
        soc.add("gender", "Gender balance", gscore, sw["gender"],
                f"{female_pct:.0f}% female workforce (balance band ~{center}%)", value=female_pct)
    else:
        soc.add("gender", "Gender balance", None, sw["gender"], "Not reported.")

    if incidents is not None:
        if fte and fte > 0:
            rate = incidents / fte * 100
            s_score = _interp(rubric["safety_anchors"], rate)
            soc.add("safety", "Workplace safety", s_score, sw["safety"],
                    f"{incidents:.0f} recordable incidents ≈ {rate:.1f} per 100 FTE", value=incidents)
        elif incidents == 0:
            soc.add("safety", "Workplace safety", 100.0, sw["safety"], "Zero recordable incidents", value=0)
        else:
            soc.add("safety", "Workplace safety", None, sw["safety"],
                    f"{incidents:.0f} incidents reported but workforce size missing — cannot normalise.")
    else:
        soc.add("safety", "Workplace safety", None, sw["safety"], "Not reported.")

    # =============================================== GOVERNANCE pillar =======
    gov = _SubScores()
    gw = rubric["governance_weight_each"]
    for metric_code, key, label in GOVERNANCE_METRICS:
        present = is_present(metric_code)
        if present is None:
            gov.add(key, label, None, gw, "Not reported.")
        else:
            gov.add(key, label, 100.0 if present else 0.0, gw,
                    "In place" if present else "Not in place", value=bool(present))

    # =============================================== plausibility checks =====
    for name, val, vp in (("Renewable share", renewable, "environmental"),
                          ("Recycling rate", recycling, "environmental"),
                          ("Female workforce", female_pct, "social")):
        if val is not None and (val < 0 or val > 100):
            flag("critical", "out_of_range", f"{name} reported as {val} — outside 0–100%. Reject and re-collect.",
                 pillar=vp)
    if incidents is not None and incidents < 0:
        flag("critical", "negative_incidents", "Negative incident count reported — invalid data.", pillar="social")
    if fte is not None and fte == 0 and ghg:
        flag("warn", "zero_fte", "Emissions reported with zero employees — verify workforce figure.",
             pillar="environmental")
    if ghg and ghg > 0 and (elec in (None, 0)) and (fuel in (None, 0)):
        flag("warn", "ghg_without_energy",
             "GHG emissions reported without any underlying energy data — basis of the figure is unverifiable.",
             pillar="environmental")
    if fte and fte > 0 and ghg and (ghg / fte) > rubric["extreme_per_capita_tco2e"]:
        flag("warn", "extreme_per_capita",
             f"~{ghg / fte:,.0f} tCO2e per employee is implausibly high — check units (tonnes vs kg).",
             pillar="environmental")
    if ghg and ghg > 0 and ((elec or 0) > 0 or (fuel or 0) > 0):
        r_ghg = by_metric.get(M_GHG)
        reasoning = (r_ghg.interpretation_reasoning or "") if r_ghg else ""
        if not reasoning.startswith("Atlas estimated"):  # human-reported, not our own estimate
            est_t = ((elec or 0) * rubric["elec_kgco2e_per_kwh"]
                     + (fuel or 0) * rubric["diesel_kgco2e_per_litre"]) / 1000.0
            if est_t > 0:
                divergence = abs(ghg - est_t) / max(ghg, est_t)
                if divergence > 0.5:
                    flag("info", "ghg_estimate_divergence",
                         f"Reported emissions ({ghg:,.1f} tCO2e) differ {divergence*100:.0f}% from the "
                         f"energy-based estimate ({est_t:,.1f} tCO2e).", pillar="environmental")

    # =============================================== aggregate ===============
    all_pillar_perf = {
        "environmental": env.pillar_score(),
        "social": soc.pillar_score(),
        "governance": gov.pillar_score(),
    }
    pillar_perf = {p: s for p, s in all_pillar_perf.items() if p in allowed}
    avail = {p: s for p, s in pillar_perf.items() if s is not None}
    if avail:
        wsum = sum(pillar_weights[p] for p in avail)
        performance = sum(s * pillar_weights[p] for p, s in avail.items()) / wsum
    else:
        performance = None

    scoped_qs = [q for q in questions if q["pillar"] in allowed]
    total = len(scoped_qs)
    approved_ids = {r.question_id for r in responses if r.status == "approved"}
    scoped_approved = {qid for qid in approved_ids if qpillar.get(qid) in allowed}
    completeness = round(len(scoped_approved) / total * 100) if total else 0
    pillar_completeness: Dict[str, int] = {}
    for pillar in allowed:
        qs = [q for q in scoped_qs if q["pillar"] == pillar]
        n = sum(1 for q in qs if q["id"] in approved_ids)
        pillar_completeness[pillar] = round(n / len(qs) * 100) if qs else 0

    scoped_flags = [f for f in flags if f.get("pillar") in allowed or f.get("pillar") == "general"]

    approved_resps = [r for r in responses
                      if r.status == "approved" and qpillar.get(r.question_id) in allowed]
    confidence = (round(sum(r.interpretation_confidence for r in approved_resps)
                        / len(approved_resps) * 100) if approved_resps else 0)
    penalties = rubric["trust_penalties"]
    penalty = sum(penalties.get(f["severity"], 0) for f in scoped_flags)
    plausibility = _clamp(100 - penalty)
    mix = rubric["trust_mix"]
    data_trust = round(mix["confidence"] * confidence + mix["plausibility"] * plausibility) if approved_resps else 0

    provisional = completeness < rubric["provisional_completeness_below"]
    if provisional and performance is not None:
        scoped_flags.append({
            "severity": "info", "code": "low_coverage", "pillar": "general",
            "message": f"Only {completeness}% of disclosures completed — performance score is provisional.",
        })

    perf_rounded = None if performance is None else round(performance)
    breakdown = {"environmental": env.items, "social": soc.items, "governance": gov.items}

    return {
        "performance_score": perf_rounded,
        "grade": grade_for(perf_rounded),
        "completeness_score": completeness,
        "data_trust_score": data_trust,
        "provisional": provisional,
        "pillar_performance": {p: (None if s is None else round(s)) for p, s in pillar_perf.items()},
        "pillar_completeness": pillar_completeness,
        "carbon_benchmark": carbon_detail if "environmental" in allowed else None,
        "flags": scoped_flags,
        "breakdown": {p: items for p, items in breakdown.items() if p in allowed},
        "trust_components": {"confidence": confidence, "plausibility": round(plausibility)},
        "methodology": {
            "version": "atlas_esg_v2",
            "pillar_weights": pillar_weights,
            "benchmark_source": bench["_meta"]["carbon_intensity"]["sources"],
            "benchmark_confidence": bench["_meta"]["carbon_intensity"]["confidence"],
        },
    }
