"""
Email client module for connecting to IMAP servers and fetching emails.
Supports both traditional IMAP authentication and OAuth2.
"""

import imaplib
import email
import base64
from email.header import decode_header
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import os


# Well-known IMAP servers for OAuth providers
OAUTH_PROVIDERS = {
    "gmail": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
    },
    "google": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
    },
    "microsoft": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
    },
    "outlook": {
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

        # Determine authentication type
        self.auth_type = account_config.get("auth_type", "imap").lower()
        self.is_oauth = self.auth_type == "oauth"

        if self.is_oauth:
            # OAuth account - use well-known provider settings
            provider = account_config.get("provider", "").lower()
            if provider in OAUTH_PROVIDERS:
                provider_config = OAUTH_PROVIDERS[provider]
                self.server = account_config.get("imap_server", provider_config["imap_server"])
                self.port = account_config.get("imap_port", provider_config["imap_port"])
            else:
                # Provider not recognized, require explicit server config
                self.server = account_config.get("imap_server", "")
                self.port = account_config.get("imap_port", 993)
                if not self.server:
                    raise ValueError(
                        f"OAuth account '{self.name}' requires either a known provider "
                        f"(gmail, microsoft, outlook) or explicit imap_server configuration"
                    )

            self.username = account_config.get("username", self.email_address)

            # Get OAuth token from config or environment variable
            self.oauth_token = account_config.get("oauth_token", "")
            if not self.oauth_token:
                env_var = f"{self.name.upper().replace(' ', '_')}_OAUTH_TOKEN"
                self.oauth_token = os.environ.get(env_var, "")

            self.password = ""  # Not used for OAuth
        else:
            # Traditional IMAP account
            self.server = account_config["imap_server"]
            self.port = account_config.get("imap_port", 993)
            self.username = account_config["username"]

            # Get password from config or environment variable
            self.password = account_config.get("password", "")
            if not self.password:
                env_var = f"{self.name.upper().replace(' ', '_')}_EMAIL_PASSWORD"
                self.password = os.environ.get(env_var, "")

            self.oauth_token = ""  # Not used for IMAP

        self.connection: Optional[imaplib.IMAP4_SSL] = None

    def _generate_oauth2_string(self, username: str, access_token: str) -> str:
        """Generate the XOAUTH2 authentication string."""
        auth_string = f"user={username}\x01auth=Bearer {access_token}\x01\x01"
        return base64.b64encode(auth_string.encode()).decode()

    def connect(self) -> bool:
        """Connect to the IMAP server."""
        try:
            self.connection = imaplib.IMAP4_SSL(self.server, self.port)

            if self.is_oauth:
                # Use XOAUTH2 authentication
                if not self.oauth_token:
                    print(f"No OAuth token configured for {self.name}")
                    return False
                auth_string = self._generate_oauth2_string(self.username, self.oauth_token)
                self.connection.authenticate("XOAUTH2", lambda x: auth_string.encode())
            else:
                # Use traditional login
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

    def _get_email_preview(self, msg: email.message.Message, length: int = 100) -> str:
        """Extract a text preview from the email body."""
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

        # Clean up and truncate
        body = " ".join(body.split())
        return body[:length] + "..." if len(body) > length else body

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
                    _, msg_data = self.connection.fetch(num, "(RFC822 FLAGS)")
                    if not msg_data or not msg_data[0]:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Check if read
                    flags_data = msg_data[0][0].decode() if isinstance(msg_data[0][0], bytes) else str(msg_data[0][0])
                    is_read = "\\Seen" in flags_data

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
                        uid=num.decode() if isinstance(num, bytes) else str(num),
                        account_name=self.name,
                        sender=sender,
                        subject=subject,
                        date=date,
                        preview=preview,
                        is_read=is_read,
                        folder=folder
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
