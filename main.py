#!/usr/bin/env python3
"""
Email Triage System - CLI interface for managing multiple email accounts.
"""

import argparse
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm

from email_client import EmailClient, Email, create_email_client
from triage import TriageEngine, Priority, TriageResult
from gmail_oauth import (
    authenticate_account,
    check_account_authenticated,
    remove_account_token,
    OAUTH_CREDENTIALS_FILE,
    CREDENTIALS_DIR,
)


console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("Copy config.example.yaml to config.yaml and fill in your account details.")
        sys.exit(1)

    with open(path) as f:
        return yaml.safe_load(f)


def display_summary(summary: dict, title: str = "Email Summary"):
    """Display a summary panel."""
    text = Text()
    text.append(f"Total: {summary['total']} emails\n", style="bold")
    text.append(f"Unread: {summary['unread']}\n\n", style="yellow")

    text.append("By Priority:\n", style="bold")
    for priority, count in summary["by_priority"].items():
        if count > 0:
            color = Priority[priority].color
            text.append(f"  {priority}: {count}\n", style=color)

    text.append("\nBy Account:\n", style="bold")
    for account, count in summary["by_account"].items():
        text.append(f"  {account}: {count}\n")

    console.print(Panel(text, title=title, border_style="blue"))


def display_emails_table(results: dict[Priority, list[TriageResult]], show_all: bool = False):
    """Display emails in a formatted table grouped by priority."""
    for priority in Priority:
        emails = results[priority]
        if not emails:
            continue

        table = Table(
            title=f"{priority.name} ({len(emails)} emails)",
            title_style=priority.color,
            show_header=True,
            header_style="bold"
        )

        table.add_column("", width=1)  # Read status
        table.add_column("Account", width=12)
        table.add_column("From", width=25)
        table.add_column("Subject", width=40)
        table.add_column("Date", width=16)

        # Show max 10 per category unless show_all
        display_emails = emails if show_all else emails[:10]

        for result in display_emails:
            email = result.email
            status = " " if email.is_read else "*"
            status_style = "dim" if email.is_read else "bold yellow"

            # Truncate fields for display
            sender = email.sender[:25] if len(email.sender) > 25 else email.sender
            subject = email.subject[:40] if len(email.subject) > 40 else email.subject

            table.add_row(
                Text(status, style=status_style),
                email.account_name,
                sender,
                subject,
                email.date.strftime("%Y-%m-%d %H:%M")
            )

        console.print(table)

        if len(emails) > 10 and not show_all:
            console.print(f"  [dim]... and {len(emails) - 10} more. Use --all to show all.[/dim]\n")


def display_email_detail(result: TriageResult):
    """Display detailed view of a single email."""
    email = result.email
    text = Text()
    text.append(f"From: ", style="bold")
    text.append(f"{email.sender}\n")
    text.append(f"Subject: ", style="bold")
    text.append(f"{email.subject}\n")
    text.append(f"Date: ", style="bold")
    text.append(f"{email.date}\n")
    text.append(f"Account: ", style="bold")
    text.append(f"{email.account_name}\n")
    text.append(f"Priority: ", style="bold")
    text.append(f"{result.priority.name}\n", style=result.priority.color)
    text.append(f"Category: ", style="bold")
    text.append(f"{result.category}\n")
    text.append(f"\nPreview:\n", style="bold")
    text.append(email.preview or "(No preview available)")

    console.print(Panel(text, title="Email Details", border_style="green"))


def fetch_all_emails(config: dict, unread_only: bool = False) -> list[Email]:
    """Fetch emails from all configured accounts."""
    all_emails = []
    limit = config.get("display", {}).get("max_emails_per_account", 50)

    for account_config in config.get("accounts", []):
        console.print(f"[dim]Fetching from {account_config['name']}...[/dim]")
        client = create_email_client(account_config)

        with client:
            emails = client.fetch_emails(limit=limit, unread_only=unread_only)
            all_emails.extend(emails)
            console.print(f"  [green]Found {len(emails)} emails[/green]")

    return all_emails


def cmd_triage(args, config: dict):
    """Run the triage command."""
    console.print("\n[bold blue]Email Triage System[/bold blue]\n")

    # Fetch emails
    emails = fetch_all_emails(config, unread_only=args.unread)

    if not emails:
        console.print("[yellow]No emails found.[/yellow]")
        return

    # Run triage
    engine = TriageEngine()
    if "triage_rules" in config:
        engine.load_rules_from_config(config["triage_rules"])

    results = engine.triage_batch(emails)
    summary = engine.get_summary(results)

    # Display results
    console.print()
    display_summary(summary)
    console.print()
    display_emails_table(results, show_all=args.all)


def cmd_interactive(args, config: dict):
    """Run interactive triage mode."""
    console.print("\n[bold blue]Interactive Email Triage[/bold blue]\n")

    emails = fetch_all_emails(config, unread_only=True)

    if not emails:
        console.print("[green]No unread emails to process![/green]")
        return

    engine = TriageEngine()
    if "triage_rules" in config:
        engine.load_rules_from_config(config["triage_rules"])

    results = [engine.triage(email) for email in emails]

    # Sort by priority
    results.sort(key=lambda r: r.priority.value)

    console.print(f"[bold]Processing {len(results)} unread emails...[/bold]\n")

    for i, result in enumerate(results, 1):
        console.print(f"\n[bold]Email {i}/{len(results)}[/bold]")
        display_email_detail(result)

        action = Prompt.ask(
            "\nAction",
            choices=["s", "n", "q"],
            default="n"
        )

        if action == "s":
            console.print("[dim]Skipped[/dim]")
        elif action == "q":
            console.print("[yellow]Exiting interactive mode.[/yellow]")
            break
        else:
            console.print("[green]Moving to next...[/green]")

    console.print("\n[bold green]Interactive triage complete![/bold green]")


def cmd_accounts(args, config: dict):
    """List configured accounts."""
    table = Table(title="Configured Email Accounts", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Email")
    table.add_column("Server")
    table.add_column("Auth Type")

    for account in config.get("accounts", []):
        auth_type = account.get("auth_type", "password")
        # Get server - may be explicit or inferred from OAuth provider
        server = account.get("imap_server", "")
        if not server and auth_type == "oauth":
            provider = account.get("oauth_provider", "")
            server = f"[{provider}]" if provider else "[auto-detect]"

        table.add_row(
            account["name"],
            account["email"],
            server,
            auth_type
        )

    console.print(table)


def cmd_test(args, config: dict):
    """Test connection to all accounts."""
    console.print("\n[bold]Testing email account connections...[/bold]\n")

    for account_config in config.get("accounts", []):
        name = account_config["name"]
        auth_type = account_config.get("auth_type", "imap")
        console.print(f"Testing {name} ({auth_type})... ", end="")

        client = create_email_client(account_config)
        if client.connect():
            folders = client.get_folder_list()
            client.disconnect()
            console.print(f"[green]OK[/green] ({len(folders)} folders)")
        else:
            console.print("[red]FAILED[/red]")


def cmd_auth(args, config: dict):
    """Set up OAuth authentication for Gmail accounts."""
    console.print("\n[bold blue]Gmail OAuth Authentication Setup[/bold blue]\n")

    # Check if credentials file exists
    if not OAUTH_CREDENTIALS_FILE.exists():
        console.print("[red]Google OAuth credentials file not found![/red]\n")
        console.print("Please copy your OAuth credentials JSON file to:")
        console.print(f"  [cyan]{OAUTH_CREDENTIALS_FILE}[/cyan]\n")
        console.print("To get credentials:")
        console.print("1. Go to Google Cloud Console (console.cloud.google.com)")
        console.print("2. Create a project and enable Gmail API")
        console.print("3. Create OAuth 2.0 credentials (Desktop app)")
        console.print("4. Download the JSON file")
        return

    # Get OAuth accounts
    oauth_accounts = [
        acc for acc in config.get("accounts", [])
        if acc.get("auth_type") == "oauth"
    ]

    if not oauth_accounts:
        console.print("[yellow]No OAuth accounts configured.[/yellow]")
        console.print("Add accounts with 'auth_type: oauth' to your config.yaml")
        return

    # Show account status
    table = Table(title="Gmail Accounts", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Email")
    table.add_column("Status")

    for account in oauth_accounts:
        is_auth = check_account_authenticated(account["name"])
        status = "[green]Authenticated[/green]" if is_auth else "[yellow]Not authenticated[/yellow]"
        table.add_row(account["name"], account["email"], status)

    console.print(table)
    console.print()

    if args.status:
        return

    if args.logout:
        # Remove all tokens
        for account in oauth_accounts:
            if remove_account_token(account["name"]):
                console.print(f"[green]Removed credentials for {account['name']}[/green]")
        return

    # Authenticate accounts
    if args.account:
        # Authenticate specific account
        account = next((a for a in oauth_accounts if a["name"] == args.account), None)
        if not account:
            console.print(f"[red]Account '{args.account}' not found or not an OAuth account[/red]")
            return
        accounts_to_auth = [account]
    else:
        # Authenticate all unauthenticated accounts
        accounts_to_auth = [
            a for a in oauth_accounts
            if not check_account_authenticated(a["name"])
        ]

    if not accounts_to_auth:
        console.print("[green]All accounts are already authenticated![/green]")
        return

    console.print(f"[bold]Authenticating {len(accounts_to_auth)} account(s)...[/bold]\n")

    for account in accounts_to_auth:
        console.print(f"\n[bold]Account: {account['name']} ({account['email']})[/bold]")
        creds = authenticate_account(account["name"], account["email"])
        if creds:
            console.print(f"[green]Successfully authenticated {account['name']}[/green]")
        else:
            console.print(f"[red]Failed to authenticate {account['name']}[/red]")

    console.print("\n[bold green]Authentication setup complete![/bold green]")


def main():
    parser = argparse.ArgumentParser(
        description="Email Triage System - Manage multiple email accounts efficiently"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Triage command
    triage_parser = subparsers.add_parser("triage", help="Triage emails from all accounts")
    triage_parser.add_argument("--unread", "-u", action="store_true", help="Only show unread emails")
    triage_parser.add_argument("--all", "-a", action="store_true", help="Show all emails (not truncated)")

    # Interactive command
    interactive_parser = subparsers.add_parser("interactive", help="Interactive triage mode")

    # Accounts command
    accounts_parser = subparsers.add_parser("accounts", help="List configured accounts")

    # Test command
    test_parser = subparsers.add_parser("test", help="Test connection to all accounts")

    # Auth command
    auth_parser = subparsers.add_parser("auth", help="Set up Gmail OAuth authentication")
    auth_parser.add_argument("--status", "-s", action="store_true", help="Show authentication status only")
    auth_parser.add_argument("--account", "-a", type=str, help="Authenticate specific account by name")
    auth_parser.add_argument("--logout", action="store_true", help="Remove stored credentials for all accounts")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    config = load_config(args.config)

    commands = {
        "triage": cmd_triage,
        "interactive": cmd_interactive,
        "accounts": cmd_accounts,
        "test": cmd_test,
        "auth": cmd_auth,
    }

    if args.command in commands:
        commands[args.command](args, config)


if __name__ == "__main__":
    main()
