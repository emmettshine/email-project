"""
Slack integration for posting email digests.
"""

import html
import os
import re
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

        # Count actionable emails for the fallback text
        actionable_count = len(results.get(Priority.URGENT, [])) + len(results.get(Priority.IMPORTANT, []))

        try:
            response = self.client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text=f"Email Digest: {actionable_count} emails need attention",
                unfurl_links=False,
                unfurl_media=False
            )
            return {"success": True, "ts": response["ts"], "channel": response["channel"]}
        except SlackApiError as e:
            return {"success": False, "error": str(e.response["error"])}

    def _extract_sender_name(self, sender: str) -> str:
        """Extract just the name from a sender string like 'John Doe <john@example.com>'."""
        # Try to match "Name <email>" pattern
        match = re.match(r'^"?([^"<]+)"?\s*<', sender)
        if match:
            return match.group(1).strip()

        # Try to match just an email and extract the name part
        match = re.match(r'^([^@]+)@', sender)
        if match:
            # Convert "john.doe" to "John Doe"
            name = match.group(1).replace('.', ' ').replace('_', ' ')
            return name.title()

        # Fallback to the original
        return sender.split('<')[0].strip().strip('"')

    def _extract_sender_domain(self, sender: str) -> str:
        """Extract the domain from a sender email address."""
        # Try to find email in angle brackets
        match = re.search(r'<([^>]+)>', sender)
        if match:
            email = match.group(1)
        else:
            # Assume the whole string is an email
            email = sender.strip()

        # Extract domain
        if '@' in email:
            return email.split('@')[1].lower()
        return ""

    def _generate_summary(self, preview: str) -> str:
        """Generate a 1-sentence summary from the email preview."""
        if not preview:
            return "No preview available."

        # Clean up the preview text
        preview = preview.strip()

        # If preview is already short, use it as-is
        if len(preview) <= 150:
            # Make sure it ends with proper punctuation
            if preview and preview[-1] not in '.!?':
                preview += '.'
            return preview

        # Find the first sentence
        sentence_end = re.search(r'[.!?](?:\s|$)', preview)
        if sentence_end and sentence_end.end() <= 200:
            return preview[:sentence_end.end()].strip()

        # Truncate at a word boundary
        truncated = preview[:147]
        last_space = truncated.rfind(' ')
        if last_space > 100:
            truncated = truncated[:last_space]
        return truncated + '...'

    def _generate_gmail_link(self, email) -> str:
        """Generate a Gmail link for the email using subject search + message ID."""
        # Format: https://mail.google.com/mail/u/{account_index}/#search/subject:{subject}/{message_id}
        from urllib.parse import quote

        # Get account index (u/0, u/1, etc.)
        account_index = getattr(email, 'gmail_account_index', 0)

        # URL encode the subject - replace spaces with +
        subject = email.subject.replace(' ', '+')
        # Quote special characters but keep + for spaces
        encoded_subject = quote(subject, safe='+')

        # Get the message ID
        message_id = getattr(email, 'message_id', '') or email.uid

        return f"https://mail.google.com/mail/u/{account_index}/#search/subject:{encoded_subject}/{message_id}"

    def _build_digest_blocks(
        self,
        results: dict[Priority, list[TriageResult]],
        summary: dict
    ) -> list[dict]:
        """Build Slack Block Kit blocks for the digest."""
        blocks = []

        # Header
        timestamp = datetime.now().strftime("%A, %B %d at %I:%M %p")
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📧 Email Digest",
                "emoji": True
            }
        })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{timestamp}_"}]
        })

        blocks.append({"type": "divider"})

        # Group emails by account, filtered to only URGENT and IMPORTANT
        actionable_priorities = [Priority.URGENT, Priority.IMPORTANT]
        emails_by_account: dict[str, list[tuple[Priority, TriageResult]]] = {}

        for priority in actionable_priorities:
            for result in results.get(priority, []):
                account = result.email.account_name
                if account not in emails_by_account:
                    emails_by_account[account] = []
                emails_by_account[account].append((priority, result))

        if not emails_by_account:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "✅ *No urgent or important emails right now!*"
                }
            })
        else:
            # Priority labels
            priority_labels = {
                Priority.URGENT: "🔴 URGENT",
                Priority.IMPORTANT: "🟡 IMPORTANT",
            }

            # Process each account
            for account_name, account_emails in emails_by_account.items():
                # Account header section
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📁 *{account_name}*"
                    }
                })

                # Sort by priority (URGENT first)
                account_emails.sort(key=lambda x: x[0].value)

                # Each email in this account - as separate blocks for clear separation
                for priority, result in account_emails:
                    email = result.email
                    priority_label = priority_labels.get(priority, "📧")

                    sender_name = self._extract_sender_name(email.sender)
                    sender_domain = self._extract_sender_domain(email.sender)
                    # Decode HTML entities (e.g., &#39; -> ', &amp; -> &)
                    subject = html.unescape(email.subject)
                    summary_text = html.unescape(self._generate_summary(email.preview))
                    gmail_link = self._generate_gmail_link(email)

                    # Build the email block with clear formatting
                    # Show account name with sender domain for context
                    account_label = f"{account_name}"
                    if sender_domain:
                        account_label += f" ({sender_domain})"

                    email_text = f"*{priority_label}* · {account_label}\n"
                    email_text += f"*From:* {sender_name}\n"
                    email_text += f"*Subject:* {subject}\n"
                    email_text += f"_{summary_text}_\n"
                    email_text += f"<{gmail_link}|📬 Open in Gmail>"

                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": email_text}
                    })

                    # Add spacing between emails
                    blocks.append({
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": " "}]
                    })

                # Divider after each account section
                blocks.append({"type": "divider"})

        # Footer
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "Powered by Email Optimizer 3000"
            }]
        })

        return blocks

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
