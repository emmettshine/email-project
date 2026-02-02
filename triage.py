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
        """Build default triage rules.

        Order matters! We check promotional/automated FIRST to filter them out
        before they can match urgent/important keywords.
        """
        # FIRST: Newsletter/promotional rules - must catch these before urgent/important
        newsletter = TriageRule("newsletters", Priority.NEWSLETTER)
        newsletter.conditions = [
            self._make_from_contains([
                "newsletter", "digest@", "weekly@", "marketing@",
                "substack.com", "mailchimp.com", "campaign-", "bulk@",
                "news@", "updates@", "announce@", "promo@", "deals@",
                "offers@", "sales@", "shop@", "store@", "rewards@",
                "fandango", "uber.com", "lyft.com", "doordash",
                "grubhub", "postmates", "instacart"
            ]),
            self._make_subject_contains([
                "unsubscribe", "weekly digest", "monthly update", "newsletter",
                "weekly roundup", "daily brief", "this week in"
            ]),
            self._is_promotional_email,
        ]
        self.rules.append(newsletter)

        # SECOND: Low priority rules - automated notifications, receipts, rewards
        low = TriageRule("low_priority", Priority.LOW)
        low.conditions = [
            self._make_from_contains([
                "notifications@", "alerts@", "no-reply@", "noreply@",
                "mailer-daemon", "postmaster@", "donotreply@",
                "notify@", "notification@", "automated@", "system@",
                "orders@", "receipts@", "confirmation@", "shipping@",
                "support@", "helpdesk@", "ticket@", "rewards@",
                "points@", "loyalty@", "members@"
            ]),
            self._make_subject_contains([
                "automated", "notification", "auto-reply", "out of office",
                "receipt", "order confirmation", "shipping confirmation",
                "password reset", "verify your", "confirm your",
                "your order", "has shipped", "tracking number",
                "successfully", "has been processed", "earned points",
                "thanks for", "thank you for your", "your purchase",
                "your recent", "your ticket", "your reservation"
            ]),
            self._is_automated_email,
            self._is_receipt_or_reward,
        ]
        self.rules.append(low)

        # THIRD: Urgent rules - but ONLY if not promotional/automated
        # These are checked AFTER newsletter/low, so promos won't match
        urgent = TriageRule("urgent", Priority.URGENT)
        urgent.conditions = [
            self._is_urgent_human_email,
        ]
        self.rules.append(urgent)

        # FOURTH: Important rules - direct human messages only
        important = TriageRule("important", Priority.IMPORTANT)
        important.conditions = [
            self._is_direct_human_message,
        ]
        self.rules.append(important)

    def _is_automated_email(self, email: Email) -> bool:
        """Detect automated/system emails."""
        sender_lower = email.sender.lower()
        subject_lower = email.subject.lower()

        # Check for common automated sender patterns
        automated_patterns = [
            "via ", "on behalf of", "@github.com", "@gitlab.com",
            "@jira.", "@atlassian.", "@slack.com", "@trello.com",
            "@asana.com", "@monday.com", "@notion.so",
            "@stripe.com", "@paypal.com", "@square.com",
            "@calendly.com", "@zoom.us", "@dropbox.com",
            "@google.com", "@docs.google.com"
        ]
        if any(p in sender_lower for p in automated_patterns):
            return True

        # Check for automated subject patterns
        auto_subjects = [
            "invited you to", "shared with you", "commented on",
            "mentioned you", "assigned to you", "new comment",
            "reminder:", "re: reminder", "calendar:", "event:"
        ]
        if any(p in subject_lower for p in auto_subjects):
            return True

        return False
    _is_automated_email.__doc__ = "Automated/system email detected"

    def _is_promotional_email(self, email: Email) -> bool:
        """Detect promotional/marketing emails."""
        sender_lower = email.sender.lower()
        subject_lower = email.subject.lower()
        preview_lower = (email.preview or "").lower()

        # Promotional sender patterns
        promo_sender_patterns = [
            "promo@", "deals@", "offers@", "sales@",
            "shop@", "store@", "info@", "hello@",
            "marketing@", "promotions@", "rewards@"
        ]

        # Promotional subject patterns - be aggressive here
        promo_subject_patterns = [
            "% off", "sale", "discount", "deal", "offer",
            "limited time", "exclusive", "free shipping",
            "don't miss", "last day", "flash sale", "clearance",
            "save $", "save up to", "coupon", "promo code",
            "last chance", "final hours", "ends today", "ends soon",
            "hurry", "act now", "special offer", "bonus",
            "reward", "points", "earn ", "redeem",
            "up to $", "only $", "just $", "now $", "was $"
        ]

        # Check subject for promotional patterns
        if any(p in subject_lower for p in promo_subject_patterns):
            return True

        # Check if sender is promotional
        if any(p in sender_lower for p in promo_sender_patterns):
            return True

        # Check preview for promotional language
        promo_preview_patterns = [
            "shop now", "buy now", "order now", "get yours",
            "limited stock", "while supplies last", "members only"
        ]
        if any(p in preview_lower for p in promo_preview_patterns):
            return True

        return False
    _is_promotional_email.__doc__ = "Promotional/marketing email detected"

    def _is_receipt_or_reward(self, email: Email) -> bool:
        """Detect receipts, order confirmations, and reward/points emails."""
        sender_lower = email.sender.lower()
        subject_lower = email.subject.lower()

        # Receipt/transaction senders
        receipt_senders = [
            "receipt", "order", "invoice", "billing",
            "transaction", "purchase", "payment",
            "fandango", "ticketmaster", "stubhub",
            "uber", "lyft", "doordash", "grubhub",
            "amazon", "ebay", "etsy", "shopify"
        ]

        # Receipt/reward subjects
        receipt_subjects = [
            "receipt", "order confirm", "purchase confirm",
            "your order", "order #", "invoice #",
            "payment received", "transaction",
            "earned points", "reward", "loyalty",
            "thanks for your order", "thank you for your purchase",
            "your tickets", "e-ticket", "booking confirm"
        ]

        if any(p in sender_lower for p in receipt_senders):
            return True

        if any(p in subject_lower for p in receipt_subjects):
            return True

        return False
    _is_receipt_or_reward.__doc__ = "Receipt or rewards email detected"

    def _is_urgent_human_email(self, email: Email) -> bool:
        """Detect genuinely urgent emails from real humans."""
        sender_lower = email.sender.lower()
        subject_lower = email.subject.lower()

        # First, exclude all promotional/automated senders
        if self._is_promotional_email(email):
            return False
        if self._is_automated_email(email):
            return False
        if self._is_receipt_or_reward(email):
            return False

        # Urgent keywords - but only from real humans
        urgent_patterns = [
            "urgent", "asap", "emergency", "action required",
            "immediate", "time sensitive", "deadline",
            "need by", "due by", "respond by", "critical"
        ]

        # Check if subject has urgent keywords
        if any(p in subject_lower for p in urgent_patterns):
            return True

        # Check for known important senders (boss, founders, etc.)
        important_senders = [
            "ceo@", "cto@", "founder@", "cofounder@",
            "president@", "director@", "vp@"
        ]
        if any(p in sender_lower for p in important_senders):
            return True

        return False
    _is_urgent_human_email.__doc__ = "Urgent email from real person"

    def _is_direct_human_message(self, email: Email) -> bool:
        """Detect direct messages from real humans (not automated).

        This is strict - we only want actual human conversations.
        """
        sender_lower = email.sender.lower()
        subject_lower = email.subject.lower()
        preview_lower = (email.preview or "").lower()

        # First, exclude all automated/promotional/receipt emails
        if self._is_promotional_email(email):
            return False
        if self._is_automated_email(email):
            return False
        if self._is_receipt_or_reward(email):
            return False

        # Exclude known automated senders
        automated_domains = [
            "@github.com", "@gitlab.com", "@jira.", "@slack.com",
            "@trello.com", "@asana.com", "@notion.so", "@calendly.com",
            "@zoom.us", "@stripe.com", "@paypal.com", "@shopify.com",
            "@mailchimp.com", "@substack.com", "@medium.com",
            "noreply@", "no-reply@", "donotreply@", "notifications@",
            "alerts@", "mailer-daemon", "postmaster@", "support@",
            "help@", "info@", "contact@", "team@", "hello@"
        ]
        if any(p in sender_lower for p in automated_domains):
            return False

        # Exclude newsletter patterns
        newsletter_patterns = ["newsletter", "digest", "weekly", "unsubscribe", "view in browser"]
        if any(p in subject_lower for p in newsletter_patterns):
            return False
        if any(p in preview_lower for p in newsletter_patterns):
            return False

        # Check for personal email indicators in preview
        personal_indicators = [
            "hi ", "hey ", "hello ", "dear ", "thanks", "thank you",
            "quick question", "following up", "checking in",
            "wanted to", "can you", "could you", "would you",
            "let me know", "get back to", "your thoughts",
            "hope you", "hope this", "just wanted", "reaching out",
            "i was wondering", "do you have", "are you available"
        ]

        # If preview suggests personal communication
        if any(p in preview_lower[:150] for p in personal_indicators):
            return True

        # If it's a reply or forward (implies conversation)
        if subject_lower.startswith("re:") or subject_lower.startswith("fwd:"):
            # But not if it looks automated
            if "noreply" not in sender_lower and "no-reply" not in sender_lower:
                return True

        return False
    _is_direct_human_message.__doc__ = "Direct message from real person"

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
