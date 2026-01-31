# Email Triage System

A command-line tool for managing multiple email accounts with automatic categorization and priority sorting.

## Features

- Connect to multiple IMAP email accounts
- Automatic email categorization (urgent, important, normal, low, newsletters)
- Customizable triage rules
- Interactive processing mode
- Rich terminal output with color-coded priorities

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

1. Copy the example config:
   ```bash
   cp config.example.yaml config.yaml
   ```

2. Edit `config.yaml` with your email account details:
   ```yaml
   accounts:
     - name: "Work"
       email: "you@company.com"
       imap_server: "imap.company.com"
       imap_port: 993
       username: "you@company.com"
       password: "your-password"
   ```

3. For Gmail accounts, use an [App Password](https://myaccount.google.com/apppasswords)

### Environment Variables

Instead of storing passwords in the config file, you can use environment variables:
- `WORK_EMAIL_PASSWORD` for an account named "Work"
- `PERSONAL_EMAIL_PASSWORD` for an account named "Personal"

## Usage

### List configured accounts
```bash
python main.py accounts
```

### Test connections
```bash
python main.py test
```

### Triage all emails
```bash
python main.py triage
```

### Triage unread emails only
```bash
python main.py triage --unread
```

### Interactive mode
```bash
python main.py interactive
```

## Customizing Triage Rules

Edit the `triage_rules` section in your config:

```yaml
triage_rules:
  urgent:
    - from_contains: ["boss@", "ceo@"]
    - subject_contains: ["URGENT", "ASAP"]

  important:
    - from_contains: ["client"]
    - subject_contains: ["invoice", "deadline"]

  newsletters:
    - from_contains: ["newsletter", "noreply"]

  low_priority:
    - from_contains: ["notifications@"]
```

## Priority Levels

| Priority | Color | Description |
|----------|-------|-------------|
| URGENT | Red | Requires immediate attention |
| IMPORTANT | Yellow | Should be handled soon |
| NORMAL | White | Regular emails |
| LOW | Gray | Can wait or be batched |
| NEWSLETTER | Cyan | Subscriptions and digests |
