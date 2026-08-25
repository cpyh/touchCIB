"""规则执行引擎：按 rule_id 求值、批量求值、导出规则元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .models import RuleOutcome

RuleContext = dict


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    category: str
    description: str
    hard: bool
    check: Callable[[RuleContext], RuleOutcome]


class RuleEngine:
    """声明式规则引擎：规则是数据，求值是统一入口，结果为可序列化轨迹。"""

    def __init__(self, rules: Iterable[dict]) -> None:
        parsed = [
            Rule(
                rule_id=entry["rule_id"],
                name=entry["name"],
                category=entry["category"],
                description=entry["description"],
                hard=entry["hard"],
                check=entry["check"],
            )
            for entry in rules
        ]
        ids = [rule.rule_id for rule in parsed]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id in rule catalog")
        self._rules = {rule.rule_id: rule for rule in parsed}
        self._order = tuple(rule.rule_id for rule in parsed)

    def evaluate(self, rule_id: str, context: RuleContext) -> RuleOutcome:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise KeyError(f"unknown rule_id: {rule_id}")
        return rule.check(context)

    def evaluate_all(
        self,
        context: RuleContext,
        *,
        categories: Sequence[str] | None = None,
    ) -> list[RuleOutcome]:
        outcomes: list[RuleOutcome] = []
        for rule_id in self._order:
            rule = self._rules[rule_id]
            if categories is not None and rule.category not in categories:
                continue
            outcomes.append(rule.check(context))
        return outcomes

    def metadata(self) -> list[dict]:
        """导出规则元数据（看板规则清单用）。"""
        return [
            {
                "rule_id": self._rules[rule_id].rule_id,
                "name": self._rules[rule_id].name,
                "category": self._rules[rule_id].category,
                "description": self._rules[rule_id].description,
                "hard": self._rules[rule_id].hard,
            }
            for rule_id in self._order
        ]
