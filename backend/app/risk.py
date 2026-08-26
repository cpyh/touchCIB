from __future__ import annotations

from decimal import Decimal

AGE_SCORE = {
    "18-24": 8,
    "25-34": 10,
    "35-44": 6,
    "45-54": 0,
    "55-64": -8,
    "65+": -15,
}
INCOME_SCORE = {
    "10万以下": -10,
    "10-30万": 0,
    "30-50万": 8,
    "50万以上": 15,
}
OCCUPATION_SCORE = {
    "退休": -8,
    "个体经营": 5,
    "专业技术": 3,
    "企业职员": 0,
    "公务员": 0,
    "其他": 0,
}
RISK_LABELS = {
    "R1": "谨慎型",
    "R2": "稳健型",
    "R3": "平衡型",
    "R4": "成长型",
    "R5": "进取型",
}


def _aum_score(aum: Decimal) -> int:
    if aum < Decimal("100000"):
        return -8
    if aum < Decimal("500000"):
        return 0
    if aum < Decimal("1000000"):
        return 5
    return 10


def assess_risk(payload: dict) -> str:
    score = 50
    score += AGE_SCORE[payload["age_group"]]
    score += INCOME_SCORE[payload["income_level"]]
    score += OCCUPATION_SCORE[payload["occupation"]]
    score += _aum_score(Decimal(str(payload["aum"])))
    score = max(0, min(100, score))

    if score <= 25:
        return "R1"
    if score <= 40:
        return "R2"
    if score <= 60:
        return "R3"
    if score <= 75:
        return "R4"
    return "R5"


def risk_label(level: str) -> str:
    return RISK_LABELS.get(level, level)
