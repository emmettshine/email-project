"""
Email client module for connecting to IMAP servers and fetching emails.

Supports both traditional IMAP authentication and OAuth2 (including Gmail OAuth).
"""

import imaplib
import email
import email.message
import base64
from email.header import decode_header
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union
import os


# Default IMAP servers for common OAuth providers
OAUTH_PROVIDER_DEFAULTS = {
    "gmail": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
    },
    "google": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
    },
    "outlook": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
    },
    "microsoft": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
    },
    "office365": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
    },
}


@dataclass
class Email:
    """Represents a single email message."""
    uid: str
    account_name: str
    sender: str
    subject: str
    date: datetime
    preview: str
    is_read: bool
    folder: str
    gmail_account_index: int = 0  # Position in Gmail (u/0, u/1, etc.)
    message_id: str = ""  # Gmail message ID for URLs

    def __str__(self) -> str:
        status = " " if self.is_read else "*"
        return f"[{status}] {self.date:%Y-%m-%d %H:%M} | {self.sender[:30]:<30} | {self.subject[:50]}"


class EmailClient:
    """IMAP email client for fetching and managing emails.

    Supports both traditional IMAP authentication and OAuth2 (XOAUTH2).
    """

    def __init__(self, account_config: dict):
        self.name = account_config["name"]
        self.email_address = account_config["email"]
        self.username = account_config.get("username", account_config["email"])
        self.gmail_account_index = account_config.get("gmail_account_index", 0)

        # Determine authentication type
        self.auth_type = account_config.get("auth_type", "password").lower()
        self.is_oauth = self.auth_type == "oauth"

        # Get server settings - use provider defaults for OAuth if not specified
        if "imap_server" in account_config:
            self.server = account_config["imap_server"]
            self.port = account_config.get("imap_port", 993)
        elif self.is_oauth:
            # Try to get defaults from OAuth provider
            provider = account_config.get("oauth_provider", "").lower()
            if provider in OAUTH_PROVIDER_DEFAULTS:
                defaults = OAUTH_PROVIDER_DEFAULTS[provider]
                self.server = defaults["imap_server"]
                self.port = defaults["imap_port"]
            else:
                # Try to infer provider from email domain
                email_domain = self.email_address.split("@")[-1].lower()
                if "gmail" in email_domain or "google" in email_domain:
                    self.server = "imap.gmail.com"
                    self.port = 993
                elif "outlook" in email_domain or "hotmail" in email_domain or "live" in email_domain:
                    self.server = "outlook.office365.com"
                    self.port = 993
                else:
                    raise ValueError(
                        f"OAuth account '{self.name}' requires either 'imap_server' or "
                        f"'oauth_provider' (gmail, outlook, office365) to be specified"
                    )
        else:
            raise ValueError(
                f"Account '{self.name}' requires 'imap_server' to be specified"
            )

        # Get credentials based on auth type
        if self.is_oauth:
            # For OAuth, get access token
            self.access_token = account_config.get("access_token", "")
            if not self.access_token:
                env_var = f"{self.name.upper().replace(' ', '_')}_ACCESS_TOKEN"
                self.access_token = os.environ.get(env_var, "")
            self.password = None
        else:
            # Traditional password authentication
            self.password = account_config.get("password", "")
            if not self.password:
                env_var = f"{self.name.upper().replace(' ', '_')}_EMAIL_PASSWORD"
                self.password = os.environ.get(env_var, "")
            self.access_token = None

        self.connection: Optional[imaplib.IMAP4_SSL] = None

    def _generate_oauth2_string(self) -> str:
        """Generate the XOAUTH2 authentication string."""
        auth_string = f"user={self.username}\x01auth=Bearer {self.access_token}\x01\x01"
        return base64.b64encode(auth_string.encode()).decode()

    def connect(self) -> bool:
        """Connect to the IMAP server."""
        try:
            self.connection = imaplib.IMAP4_SSL(self.server, self.port)

            if self.is_oauth:
                # Use XOAUTH2 authentication
                auth_string = self._generate_oauth2_string()
                self.connection.authenticate("XOAUTH2", lambda x: auth_string)
            else:
                # Use traditional password authentication
                self.connection.login(self.username, self.password)

            return True
        except imaplib.IMAP4.error as e:
            print(f"Failed to connect to {self.name}: {e}")
            return False
        except Exception as e:
            print(f"Connection error for {self.name}: {e}")
            return False

    def disconnect(self):
        """Disconnect from the IMAP server."""
        if self.connection:
            try:
                self.connection.logout()
            except Exception:
                pass
            self.connection = None

    def _decode_header_value(self, value: str) -> str:
        """Decode email header value."""
        if not value:
            return ""
        decoded_parts = []
        for part, encoding in decode_header(value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(part)
        return "".join(decoded_parts)

    def _get_email_preview(self, msg: email.message.Message, length: int = 150) -> str:
        """Extract a text preview from the email body (first 2 lines or 150 chars)."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="replace")
                            break
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
            except Exception:
                body = ""

        # Get first 2 non-empty lines
        lines = [line.strip() for line in body.split('\n') if line.strip()]
        preview = ' '.join(lines[:2]) if lines else ""

        # Truncate to length if needed
        if len(preview) > length:
            preview = preview[:length-3] + "..."
        return preview

    def fetch_emails(self, folder: str = "INBOX", limit: int = 50, unread_only: bool = False) -> list[Email]:
        """Fetch emails from the specified folder."""
        if not self.connection:
            if not self.connect():
                return []

        emails = []
        try:
            self.connection.select(folder, readonly=True)

            # Search for emails
            search_criteria = "UNSEEN" if unread_only else "ALL"
            _, message_numbers = self.connection.search(None, search_criteria)

            if not message_numbers[0]:
                return []

            # Get the most recent emails
            nums = message_numbers[0].split()
            nums = nums[-limit:] if len(nums) > limit else nums
            nums.reverse()  # Most recent first

            for num in nums:
                try:
                    # Fetch email data including Gmail thread ID if available
                    # X-GM-THRID is Gmail's thread identifier (better for web URLs)
                    # Fetch email data including Gmail thread ID and message ID
                    _, msg_data = self.connection.fetch(num, "(RFC822 FLAGS X-GM-THRID X-GM-MSGID)")
                    if not msg_data or not msg_data[0]:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Check if read and extract Gmail IDs
                    flags_data = msg_data[0][0].decode() if isinstance(msg_data[0][0], bytes) else str(msg_data[0][0])
                    is_read = "\\Seen" in flags_data

                    # Extract Gmail thread ID and message ID
                    import re as re_module
                    gmail_thread_id = None
                    gmail_msg_id = None

                    thrid_match = re_module.search(r'X-GM-THRID\s+(\d+)', flags_data)
                    if thrid_match:
                        gmail_thread_id = format(int(thrid_match.group(1)), 'x')

                    msgid_match = re_module.search(r'X-GM-MSGID\s+(\d+)', flags_data)
                    if msgid_match:
                        gmail_msg_id = format(int(msgid_match.group(1)), 'x')

                    # Use Gmail thread ID if available, otherwise fall back to sequence number
                    message_uid = gmail_thread_id if gmail_thread_id else (num.decode() if isinstance(num, bytes) else str(num))

                    # Parse date
                    date_str = msg.get("Date", "")
                    try:
                        date = parsedate_to_datetime(date_str)
                    except Exception:
                        date = datetime.now()

                    # Get sender
                    sender = self._decode_header_value(msg.get("From", "Unknown"))

                    # Get subject
                    subject = self._decode_header_value(msg.get("Subject", "(No Subject)"))

                    # Get preview
                    preview = self._get_email_preview(msg)

                    emails.append(Email(
                        uid=message_uid,
                        account_name=self.name,
                        sender=sender,
                        subject=subject,
                        date=date,
                        preview=preview,
                        is_read=is_read,
                        folder=folder,
                        gmail_account_index=self.gmail_account_index,
                        message_id=gmail_msg_id or message_uid
                    ))
                except Exception as e:
                    print(f"Error parsing email: {e}")
                    continue

        except Exception as e:
            print(f"Error fetching emails from {self.name}: {e}")

        return emails

    def get_folder_list(self) -> list[str]:
        """Get list of available folders."""
        if not self.connection:
            if not self.connect():
                return []

        try:
            _, folders = self.connection.list()
            folder_names = []
            for folder in folders:
                # Parse folder name from response
                if isinstance(folder, bytes):
                    folder = folder.decode()
                parts = folder.split(' "/" ')
                if len(parts) >= 2:
                    folder_names.append(parts[-1].strip('"'))
            return folder_names
        except Exception:
            return ["INBOX"]

    def mark_as_read(self, uid: str) -> bool:
        """Mark an email as read."""
        if not self.connection:
            return False
        try:
            self.connection.select("INBOX")
            self.connection.store(uid.encode(), "+FLAGS", "\\Seen")
            return True
        except Exception:
            return False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def create_email_client(account_config: dict) -> Union["EmailClient", "GmailClient"]:
    """
    Factory function to create the appropriate email client based on auth_type.

    Args:
        account_config: Account configuration dictionary

    Returns:
        EmailClient for IMAP auth or GmailClient for OAuth
    """
    auth_type = account_config.get("auth_type", "imap")

    if auth_type == "oauth":
        from gmail_oauth import GmailClient
        return GmailClient(account_config)
    else:
        return EmailClient(account_config)
