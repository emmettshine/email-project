"""
Email triage engine for categorizing and prioritizing emails.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable
from email_client import Email


class Priority(Enum):
    """Email priority levels."""
    URGENT = 1
    IMPORTANT = 2
    NORMAL = 3
    LOW = 4
    NEWSLETTER = 5

    def __str__(self) -> str:
        return self.name.lower()

    @property
    def color(self) -> str:
        """Return color code for rich formatting."""
        colors = {
            Priority.URGENT: "red bold",
            Priority.IMPORTANT: "yellow",
            Priority.NORMAL: "white",
            Priority.LOW: "dim",
            Priority.NEWSLETTER: "cyan dim"
        }
        return colors.get(self, "white")


@dataclass
class TriageResult:
    """Result of triaging an email."""
    email: Email
    priority: Priority
    category: str
    matched_rule: str = ""


@dataclass
class TriageRule:
    """A single triage rule."""
    name: str
    priority: Priority
    conditions: list[Callable[[Email], bool]] = field(default_factory=list)

    def matches(self, email: Email) -> tuple[bool, str]:
        """Check if email matches this rule. Returns (matches, reason)."""
        for condition in self.conditions:
            result = condition(email)
            if result:
                return True, condition.__doc__ or "Rule matched"
        return False, ""


class TriageEngine:
    """Engine for categorizing emails based on rules."""

    def __init__(self):
        self.rules: list[TriageRule] = []
        self._build_default_rules()

    def _build_default_rules(self):
        """Build default triage rules."""
        # Urgent rules
        urgent = TriageRule("urgent", Priority.URGENT)
        urgent.conditions = [
            self._make_subject_contains(["URGENT", "ASAP", "EMERGENCY", "ACTION REQUIRED"]),
            self._make_from_contains(["ceo@", "cto@", "boss"]),
        ]
        self.rules.append(urgent)

        # Important rules
        important = TriageRule("important", Priority.IMPORTANT)
        important.conditions = [
            self._make_subject_contains(["invoice", "payment", "contract", "deadline"]),
            self._make_from_contains(["client", "customer", "billing"]),
        ]
        self.rules.append(important)

        # Newsletter rules
        newsletter = TriageRule("newsletters", Priority.NEWSLETTER)
        newsletter.conditions = [
            self._make_from_contains(["newsletter", "noreply@", "marketing@", "digest@"]),
            self._make_subject_contains(["unsubscribe", "weekly digest", "monthly update"]),
        ]
        self.rules.append(newsletter)

        # Low priority rules
        low = TriageRule("low_priority", Priority.LOW)
        low.conditions = [
            self._make_from_contains(["notifications@", "alerts@", "no-reply@", "mailer-daemon"]),
            self._make_subject_contains(["automated", "notification", "auto-reply"]),
        ]
        self.rules.append(low)

    def _make_from_contains(self, patterns: list[str]) -> Callable[[Email], bool]:
        """Create a condition that checks if sender contains any pattern."""
        def condition(email: Email) -> bool:
            sender_lower = email.sender.lower()
            return any(p.lower() in sender_lower for p in patterns)
        condition.__doc__ = f"Sender contains: {', '.join(patterns)}"
        return condition

    def _make_subject_contains(self, patterns: list[str]) -> Callable[[Email], bool]:
        """Create a condition that checks if subject contains any pattern."""
        def condition(email: Email) -> bool:
            subject_lower = email.subject.lower()
            return any(p.lower() in subject_lower for p in patterns)
        condition.__doc__ = f"Subject contains: {', '.join(patterns)}"
        return condition

    def load_rules_from_config(self, triage_config: dict):
        """Load additional rules from configuration."""
        priority_map = {
            "urgent": Priority.URGENT,
            "important": Priority.IMPORTANT,
            "newsletters": Priority.NEWSLETTER,
            "low_priority": Priority.LOW,
            "normal": Priority.NORMAL
        }

        for category, rules in triage_config.items():
            priority = priority_map.get(category, Priority.NORMAL)
            rule = TriageRule(category, priority)

            for rule_def in rules:
                if "from_contains" in rule_def:
                    rule.conditions.append(self._make_from_contains(rule_def["from_contains"]))
                if "subject_contains" in rule_def:
                    rule.conditions.append(self._make_subject_contains(rule_def["subject_contains"]))

            # Add to front so config rules take precedence
            self.rules.insert(0, rule)

    def triage(self, email: Email) -> TriageResult:
        """Categorize a single email."""
        for rule in self.rules:
            matches, reason = rule.matches(email)
            if matches:
                return TriageResult(
                    email=email,
                    priority=rule.priority,
                    category=rule.name,
                    matched_rule=reason
                )

        # Default to normal priority
        return TriageResult(
            email=email,
            priority=Priority.NORMAL,
            category="general",
            matched_rule="No rules matched"
        )

    def triage_batch(self, emails: list[Email]) -> dict[Priority, list[TriageResult]]:
        """Triage multiple emails and group by priority."""
        results: dict[Priority, list[TriageResult]] = {p: [] for p in Priority}

        for email in emails:
            result = self.triage(email)
            results[result.priority].append(result)

        return results

    def get_summary(self, results: dict[Priority, list[TriageResult]]) -> dict:
        """Generate a summary of triage results."""
        summary = {
            "total": sum(len(v) for v in results.values()),
            "unread": 0,
            "by_priority": {},
            "by_account": {}
        }

        for priority, triaged in results.items():
            summary["by_priority"][priority.name] = len(triaged)
            for result in triaged:
                if not result.email.is_read:
                    summary["unread"] += 1
                account = result.email.account_name
                summary["by_account"][account] = summary["by_account"].get(account, 0) + 1

        return summary
