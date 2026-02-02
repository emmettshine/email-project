"""
Slack integration for posting email digests.
"""

import os
from datetime import datetime
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from triage import Priority, TriageResult


class SlackClient:
    """Client for posting email digests to Slack."""

    def __init__(self, config: dict):
        """
        Initialize Slack client.

        Args:
            config: Slack configuration dict with 'bot_token' and 'channel' keys.
                    Token can also be set via SLACK_BOT_TOKEN environment variable.
        """
        self.token = config.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        self.default_channel = config.get("channel", "#email-digests")
        self.include_preview = config.get("include_preview", False)
        self.max_emails_per_priority = config.get("max_emails_per_priority", 5)

        if not self.token:
            raise ValueError(
                "Slack bot token not found. Set 'bot_token' in config or "
                "SLACK_BOT_TOKEN environment variable."
            )

        self.client = WebClient(token=self.token)

    def post_digest(
        self,
        results: dict[Priority, list[TriageResult]],
        summary: dict,
        channel: Optional[str] = None
    ) -> dict:
        """
        Post an email digest to Slack.

        Args:
            results: Triage results grouped by priority.
            summary: Summary statistics from triage engine.
            channel: Channel to post to (uses default if not specified).

        Returns:
            Slack API response dict.
        """
        channel = channel or self.default_channel
        blocks = self._build_digest_blocks(results, summary)

        try:
            response = self.client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=f"Email Digest: {summary['total']} emails ({summary['unread']} unread)"
            )
            return {"success": True, "ts": response["ts"], "channel": response["channel"]}
        except SlackApiError as e:
            return {"success": False, "error": str(e.response["error"])}

    def _build_digest_blocks(
        self,
        results: dict[Priority, list[TriageResult]],
        summary: dict
    ) -> list[dict]:
        """Build Slack Block Kit blocks for the digest."""
        blocks = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":envelope: Email Digest",
                "emoji": True
            }
        })

        # Summary section
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        summary_text = (
            f"*Total:* {summary['total']} emails | "
            f"*Unread:* {summary['unread']} | "
            f"*Generated:* {timestamp}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary_text}
        })

        # Account breakdown
        if summary.get("by_account"):
            account_text = " | ".join(
                f"{account}: {count}"
                for account, count in summary["by_account"].items()
            )
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"📬 {account_text}"}]
            })

        blocks.append({"type": "divider"})

        # Priority sections
        priority_emoji = {
            Priority.URGENT: "🔴",
            Priority.IMPORTANT: "🟡",
            Priority.NORMAL: "⚪",
            Priority.LOW: "🔵",
            Priority.NEWSLETTER: "📰"
        }

        for priority in Priority:
            emails = results.get(priority, [])
            if not emails:
                continue

            emoji = priority_emoji.get(priority, "📧")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{priority.name}* ({len(emails)} emails)"
                }
            })

            # List emails (limited)
            display_emails = emails[:self.max_emails_per_priority]
            email_lines = []

            for result in display_emails:
                email = result.email
                read_marker = "" if email.is_read else "• "
                sender = self._truncate(email.sender, 30)
                subject = self._truncate(email.subject, 50)
                line = f"{read_marker}*{sender}*: {subject}"

                if self.include_preview and email.preview:
                    preview = self._truncate(email.preview, 100)
                    line += f"\n   _{preview}_"

                email_lines.append(line)

            if len(emails) > self.max_emails_per_priority:
                email_lines.append(
                    f"_...and {len(emails) - self.max_emails_per_priority} more_"
                )

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(email_lines)}
            })

        # Footer
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "Generated by Email Triage System"
            }]
        })

        return blocks

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length with ellipsis."""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."

    def test_connection(self) -> dict:
        """Test the Slack connection by calling auth.test."""
        try:
            response = self.client.auth_test()
            return {
                "success": True,
                "team": response["team"],
                "user": response["user"],
                "bot_id": response.get("bot_id")
            }
        except SlackApiError as e:
            return {"success": False, "error": str(e.response["error"])}

    def list_channels(self) -> list[dict]:
        """List available channels the bot can post to."""
        try:
            response = self.client.conversations_list(
                types="public_channel,private_channel"
            )
            return [
                {"id": ch["id"], "name": ch["name"]}
                for ch in response["channels"]
                if ch.get("is_member", False)
            ]
        except SlackApiError:
            return []
