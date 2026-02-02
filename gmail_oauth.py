"""
Gmail OAuth module for authenticating with Google's Gmail API.
"""

import os
import pickle
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from email_client import Email


# Gmail API scopes - read-only access to emails
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Default paths
CREDENTIALS_DIR = Path(__file__).parent / "credentials"
OAUTH_CREDENTIALS_FILE = CREDENTIALS_DIR / "google_oauth_credentials.json"


def get_token_path(account_name: str) -> Path:
    """Get the token file path for a specific account."""
    safe_name = account_name.lower().replace(" ", "_").replace("@", "_at_")
    return CREDENTIALS_DIR / f"token_{safe_name}.pickle"


def authenticate_account(account_name: str, email_address: str) -> Optional[Credentials]:
    """
    Authenticate a Gmail account using OAuth2.

    This will open a browser window for the user to authenticate if needed.
    Tokens are cached for future use.

    Args:
        account_name: A friendly name for the account
        email_address: The Gmail address to authenticate

    Returns:
        Credentials object if successful, None otherwise
    """
    CREDENTIALS_DIR.mkdir(exist_ok=True)
    token_path = get_token_path(account_name)
    creds = None

    # Load existing token if available
    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token for {account_name}: {e}")
                creds = None

        if not creds:
            if not OAUTH_CREDENTIALS_FILE.exists():
                print(f"OAuth credentials file not found: {OAUTH_CREDENTIALS_FILE}")
                print("Please copy your Google OAuth credentials JSON file to:")
                print(f"  {OAUTH_CREDENTIALS_FILE}")
                return None

            flow = InstalledAppFlow.from_client_secrets_file(
                str(OAUTH_CREDENTIALS_FILE),
                SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob"
            )
            print(f"\nAuthenticating {account_name} ({email_address})...")
            print(f"Make sure to sign in with: {email_address}\n")

            # Generate authorization URL
            auth_url, _ = flow.authorization_url(prompt="consent")
            print("Please visit this URL in your browser:")
            print(f"\n{auth_url}\n")
            print("After authorizing, you'll see an authorization code.")
            code = input("Enter the authorization code here: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

        # Save the token for future use
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)
        print(f"Authentication successful for {account_name}!")

    return creds


def check_account_authenticated(account_name: str) -> bool:
    """Check if an account has valid stored credentials."""
    token_path = get_token_path(account_name)
    if not token_path.exists():
        return False

    try:
        with open(token_path, "rb") as token:
            creds = pickle.load(token)
        return creds and (creds.valid or creds.refresh_token)
    except Exception:
        return False


def remove_account_token(account_name: str) -> bool:
    """Remove stored credentials for an account."""
    token_path = get_token_path(account_name)
    if token_path.exists():
        token_path.unlink()
        return True
    return False


class GmailClient:
    """Gmail API client for fetching emails using OAuth2."""

    def __init__(self, account_config: dict):
        self.name = account_config["name"]
        self.email_address = account_config["email"]
        self.service = None
        self._creds = None

    def connect(self) -> bool:
        """Connect to Gmail API using OAuth2."""
        try:
            self._creds = authenticate_account(self.name, self.email_address)
            if not self._creds:
                return False

            self.service = build("gmail", "v1", credentials=self._creds)
            return True
        except Exception as e:
            print(f"Failed to connect to Gmail for {self.name}: {e}")
            return False

    def disconnect(self):
        """Disconnect from Gmail API."""
        self.service = None
        self._creds = None

    def _decode_header(self, headers: list, name: str) -> str:
        """Extract a header value from the headers list."""
        for header in headers:
            if header["name"].lower() == name.lower():
                return header["value"]
        return ""

    def _get_body_preview(self, payload: dict, length: int = 100) -> str:
        """Extract body preview from message payload."""
        body = ""

        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain" and part["body"].get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                    break

        # Clean up and truncate
        body = " ".join(body.split())
        return body[:length] + "..." if len(body) > length else body

    def fetch_emails(self, folder: str = "INBOX", limit: int = 50, unread_only: bool = False) -> list[Email]:
        """Fetch emails from Gmail using the API."""
        if not self.service:
            if not self.connect():
                return []

        emails = []
        try:
            # Build query
            query = f"in:{folder.lower()}"
            if unread_only:
                query += " is:unread"

            # List messages
            results = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=limit
            ).execute()

            messages = results.get("messages", [])

            for msg_ref in messages:
                try:
                    msg = self.service.users().messages().get(
                        userId="me",
                        id=msg_ref["id"],
                        format="full"
                    ).execute()

                    headers = msg["payload"]["headers"]

                    # Parse date
                    date_str = self._decode_header(headers, "Date")
                    try:
                        from email.utils import parsedate_to_datetime
                        date = parsedate_to_datetime(date_str)
                    except Exception:
                        # Use internal date as fallback
                        date = datetime.fromtimestamp(int(msg["internalDate"]) / 1000)

                    # Check if read
                    is_read = "UNREAD" not in msg.get("labelIds", [])

                    # Get preview
                    preview = msg.get("snippet", "")

                    # Use threadId for Gmail web URLs (works better than message ID)
                    thread_id = msg.get("threadId", msg_ref["id"])
                    subject = self._decode_header(headers, "Subject") or "(No Subject)"
                    print(f"DEBUG gmail_oauth: '{subject[:40]}' -> threadId='{thread_id}'")

                    emails.append(Email(
                        uid=thread_id,
                        account_name=self.name,
                        sender=self._decode_header(headers, "From"),
                        subject=subject,
                        date=date,
                        preview=preview,
                        is_read=is_read,
                        folder=folder
                    ))
                except HttpError as e:
                    print(f"Error fetching message: {e}")
                    continue

        except HttpError as e:
            print(f"Error fetching emails from {self.name}: {e}")

        return emails

    def get_folder_list(self) -> list[str]:
        """Get list of Gmail labels (folders)."""
        if not self.service:
            if not self.connect():
                return []

        try:
            results = self.service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            return [label["name"] for label in labels]
        except HttpError:
            return ["INBOX"]

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
