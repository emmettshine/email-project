"""
Slack client for posting email digest messages via webhook.
"""

import json
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Optional

from triage import Priority, TriageResult


class SlackClient:
    """Client for posting messages to Slack via webhook."""

    def __init__(self, config: dict):
        """
        Initialize the Slack client.

        Args:
            config: Slack configuration dict with 'webhook_url' key
        """
        self.webhook_url = config.get("webhook_url", "")
        self.channel = config.get("channel")
        self.username = config.get("username", "Email Digest Bot")
        self.icon_emoji = config.get("icon_emoji", ":email:")

    def is_configured(self) -> bool:
        """Check if the Slack client is properly configured."""
        return bool(self.webhook_url)

    def post_message(self, message: dict) -> tuple[bool, str]:
        """
        Post a message to Slack webhook.

        Args:
            message: Slack message payload

        Returns:
            Tuple of (success, error_message)
        """
        if not self.is_configured():
            return False, "Slack webhook URL not configured"

        try:
            data = json.dumps(message).encode("utf-8")
            request = Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            with urlopen(request, timeout=30) as response:
                return True, ""
        except HTTPError as e:
            return False, f"HTTP error {e.code}: {e.reason}"
        except URLError as e:
            return False, f"URL error: {e.reason}"
        except Exception as e:
            return False, f"Error posting to Slack: {str(e)}"

    def format_digest(
        self,
        results: dict[Priority, list[TriageResult]],
        summary: dict
    ) -> dict:
        """
        Format email triage results as a Slack message.

        Args:
            results: Triage results grouped by priority
            summary: Summary statistics dict

        Returns:
            Slack message payload
        """
        blocks = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Email Digest - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "emoji": True
            }
        })

        # Summary section
        summary_text = (
            f"*Total:* {summary['total']} emails | "
            f"*Unread:* {summary['unread']}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary_text}
        })

        # Priority breakdown
        priority_lines = []
        priority_emojis = {
            Priority.URGENT: ":rotating_light:",
            Priority.IMPORTANT: ":warning:",
            Priority.NORMAL: ":email:",
            Priority.LOW: ":arrow_down:",
            Priority.NEWSLETTER: ":newspaper:"
        }
        for priority in Priority:
            count = summary["by_priority"].get(priority.name, 0)
            if count > 0:
                emoji = priority_emojis.get(priority, ":email:")
                priority_lines.append(f"{emoji} *{priority.name}:* {count}")

        if priority_lines:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(priority_lines)}
            })

        # Account breakdown
        if summary.get("by_account"):
            account_text = " | ".join(
                f"*{acc}:* {cnt}"
                for acc, cnt in summary["by_account"].items()
            )
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": account_text}]
            })

        blocks.append({"type": "divider"})

        # Show urgent and important emails
        for priority in [Priority.URGENT, Priority.IMPORTANT]:
            emails = results.get(priority, [])
            if emails:
                emoji = priority_emojis.get(priority, "")
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *{priority.name} Emails:*"
                    }
                })

                # Show up to 5 emails per priority
                for result in emails[:5]:
                    email = result.email
                    email_text = (
                        f"*From:* {self._escape_text(email.sender)}\n"
                        f"*Subject:* {self._escape_text(email.subject)}\n"
                        f"_Account: {email.account_name} | "
                        f"{email.date.strftime('%Y-%m-%d %H:%M')}_"
                    )
                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": email_text}
                    })

                if len(emails) > 5:
                    blocks.append({
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": f"_...and {len(emails) - 5} more {priority.name.lower()} emails_"
                        }]
                    })

                blocks.append({"type": "divider"})

        # Footer
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Generated by Email Triage System"
            }]
        })

        message = {"blocks": blocks}

        if self.channel:
            message["channel"] = self.channel
        if self.username:
            message["username"] = self.username
        if self.icon_emoji:
            message["icon_emoji"] = self.icon_emoji

        return message

    def _escape_text(self, text: str) -> str:
        """Escape special characters for Slack mrkdwn."""
        # Escape Slack special characters
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        return text

    def post_digest(
        self,
        results: dict[Priority, list[TriageResult]],
        summary: dict
    ) -> tuple[bool, str]:
        """
        Format and post an email digest to Slack.

        Args:
            results: Triage results grouped by priority
            summary: Summary statistics dict

        Returns:
            Tuple of (success, error_message)
        """
        message = self.format_digest(results, summary)
        return self.post_message(message)
