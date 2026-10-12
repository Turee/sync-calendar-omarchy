#!/usr/bin/env python3
"""
Chronica guided setup: connect a calendar account without editing JSON.

Opens the matching page of the setup guide in the browser, asks for the one
thing the provider hands out (a sign-in, a token, an app password or a link),
checks it works, lets you pick calendars, and writes calendars.json.

  setup.py              menu
  setup.py google       jump straight to one provider (google, icloud, jmap, caldav, ics, local)
  setup.py reconnect    sign in to Google again with the saved app
"""

import getpass
import importlib.util
import os
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE = "https://promaaa.github.io/sync-calendar-omarchy/"
COLORS = ["#4285f4", "#30d158", "#ff7700", "#6d4aff", "#e01b24", "#0082c9", "#f5c211", "#a6e3a1"]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fe = load_script("fetch_events", "fetch-events.py")
ga = load_script("google_auth", "google-auth.py")


# ---- small helpers -------------------------------------------------------

def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_secret(prompt):
    return getpass.getpass(f"{prompt} (hidden): ").strip()


def open_guide(anchor):
    url = GUIDE + "#" + anchor
    print(f"\nOpening the guide: {url}")
    webbrowser.open(url)


def pick(options, label):
    """Numbered multi-choice over (title, detail) pairs. Returns chosen indexes."""
    for i, (title, detail) in enumerate(options, 1):
        print(f"  {i:>2}  {title}" + (f"  ({detail})" if detail else ""))
    while True:
        raw = input(f"{label} (e.g. 1,3; Enter = all): ").strip()
        chosen = parse_pick(raw, len(options))
        if chosen is not None:
            return chosen
        print("  Type numbers from the list, separated by commas.")


def parse_pick(raw, count):
    if not raw:
        return list(range(count))
    try:
        idx = [int(part) - 1 for part in raw.replace(" ", ",").split(",") if part]
    except ValueError:
        return None
    if not idx or any(i < 0 or i >= count for i in idx):
        return None
    return sorted(set(idx))


def window():
    now = datetime.now()
    return now - timedelta(days=45), now + timedelta(days=90)


# ---- calendars.json ------------------------------------------------------

def is_placeholder(entry):
    """The sample entry fetch-events.py writes on first run: no source at all."""
    return set(entry) <= {"name", "url", "color", "enabled"} and not str(entry.get("url", "")).strip()


def add_entries(config, entries):
    """Append entries with unique names, dropping the empty sample entry."""
    config = [c for c in config if isinstance(c, dict) and not is_placeholder(c)]
    taken = {str(c.get("name", "")).strip().lower() for c in config}
    for entry in entries:
        base, n = entry["name"], 2
        while entry["name"].lower() in taken:
            entry["name"] = f"{base} ({n})"
            n += 1
        taken.add(entry["name"].lower())
        entry.setdefault("color", COLORS[len(config) % len(COLORS)])
        entry.setdefault("enabled", True)
        config.append(entry)
    return config


def save(entries):
    config = fe.safe_load_json(fe.CONFIG_PATH, max_bytes=fe.MAX_CONFIG_BYTES) or []
    fe.save_calendars(add_entries(config, entries))  # passwords and tokens go to the keyring when one runs
    for entry in entries:
        print(f"  + {entry['name']}")
    print(f"Saved to {fe.CONFIG_PATH}")


def configured(key):
    config = fe.safe_load_json(fe.CONFIG_PATH, max_bytes=fe.MAX_CONFIG_BYTES) or []
    return {str(c.get(key, "")) for c in config if isinstance(c, dict) and c.get(key)}


# ---- providers -----------------------------------------------------------

def google_client():
    saved = ga.load_saved_auth()
    if saved.get("client_id") and saved.get("client_secret"):
        if ask("Reuse the Google app you set up before? (Y/n)", "y").lower().startswith("y"):
            return saved["client_id"], saved["client_secret"]

    found = ga.find_downloaded_client()
    if found:
        print(f"Found ~/Downloads/{found[2]}")
        if ask("Use it? (Y/n)", "y").lower().startswith("y"):
            return found[0], found[1]

    print("\nGoogle needs a small app of your own (one time, about 5 minutes).")
    open_guide("google")
    print("Follow the guide. When you download the client JSON, come back here.")
    while True:
        raw = input("Press Enter once it is in ~/Downloads, or paste the Client ID: ").strip()
        if raw:
            secret = ask_secret("Client secret")
            if secret:
                return raw, secret
            continue
        found = ga.find_downloaded_client()
        if found:
            print(f"Found ~/Downloads/{found[2]}")
            return found[0], found[1]
        print("  No client_secret_*.json in ~/Downloads yet.")


def google_calendars():
    return fe.google_list(
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        {"minAccessRole": "reader"}, fe.get_google_access_token(),
    )


def setup_google():
    client_id, client_secret = google_client()
    ga.authorize(client_id, client_secret)
    print("Signed in.\n")
    try:
        items = google_calendars()
    except Exception as exc:
        raise RuntimeError(
            f"Signed in, but listing calendars failed ({exc}). Is the Google Calendar API enabled on the project?"
        ) from exc
    have = configured("googleCalendarId")
    items = [c for c in items if c.get("id") not in have]
    if not items:
        print("Every calendar on this account is already added.")
        return []
    print("Calendars on this account:")
    options = [(c.get("summaryOverride") or c.get("summary") or c["id"],
                "primary" if c.get("primary") else c.get("accessRole", "")) for c in items]
    chosen = pick(options, "Add which")
    return [{
        "name": options[i][0],
        "googleCalendarId": items[i]["id"],
        "color": items[i].get("backgroundColor") or COLORS[0],
    } for i in chosen]


def reconnect_google():
    saved = ga.load_saved_auth()
    if not (saved.get("client_id") and saved.get("client_secret")):
        print("No Google app saved yet, starting the full Google setup.")
        return setup_google()
    ga.authorize(saved["client_id"], saved["client_secret"])
    print("Google reconnected.")
    return []


def caldav_accounts(base, username, password, label):
    probe = {"name": label, "caldavUrl": base, "username": username, "password": password}
    print("Looking up your calendars...")
    found = fe.caldav_discover(probe)
    have = configured("caldavUrl")
    found = [c for c in found if c["caldavUrl"] not in have]
    if not found:
        print("No new calendars found on this account.")
        return []
    chosen = pick([(c["name"] or c["caldavUrl"], "") for c in found], "Add which")
    return [{
        "name": found[i]["name"] or label,
        "caldavUrl": found[i]["caldavUrl"],
        "username": username,
        "password": password,
    } for i in chosen]


def setup_icloud():
    open_guide("icloud")
    print("Create an app-specific password (your Apple ID password will not work).")
    username = ask("Apple ID email")
    password = ask_secret("App-specific password (xxxx-xxxx-xxxx-xxxx)")
    return caldav_accounts(fe.CALDAV_DEFAULT_HOST, username, password, "iCloud")


def setup_caldav():
    open_guide("caldav")
    server = ask("Server address (e.g. cloud.example.com)")
    if "://" not in server:
        server = "https://" + server
    parts = urllib.parse.urlsplit(server)
    if parts.path in ("", "/"):
        # Nextcloud and ownCloud serve CalDAV here; other servers answer on the root.
        server = urllib.parse.urlunsplit(parts._replace(path="/remote.php/dav/"))
        server = ask("CalDAV address", server)
    username = ask("Username")
    password = ask_secret("App password")
    return caldav_accounts(server, username, password, parts.hostname or "CalDAV")


def setup_jmap():
    open_guide("jmap")
    url = ask("Session URL", "https://api.fastmail.com/jmap/session")
    token = ask_secret("API token")
    name = ask("Name", "Fastmail" if "fastmail" in url else "JMAP")
    entry = {"name": name, "type": "jmap", "jmapUrl": url, "jmapToken": token}
    print("Checking the token...")
    result = fe.fetch_jmap_calendar(entry, *window())
    if result["status"] != "ok":
        raise RuntimeError(f"The server did not accept it: {result['status']}")
    print(f"Works: {result['count']} events in the next weeks.")
    return [entry]


def setup_ics():
    open_guide("ics")
    url = ask("Calendar link (https://, webcal:// or .ics)")
    name = ask("Name", "Calendar")
    entry = {"name": name, "url": url}
    print("Fetching it once to check...")
    result = fe.fetch_calendar(entry, *window())
    if result["status"] != "ok":
        raise RuntimeError(f"That link did not work: {result['status']}")
    print(f"Works: {result['count']} events in the next weeks.")
    return [entry]


def setup_local():
    return [{"name": ask("Name", "Local"), "type": "local", "color": "#a6e3a1"}]


PROVIDERS = [
    ("google", "Google Calendar", "read & write, needs your own Google app (~5 min)", setup_google),
    ("icloud", "Apple iCloud", "read & write, app-specific password", setup_icloud),
    ("jmap", "Fastmail / JMAP", "read & write, API token", setup_jmap),
    ("caldav", "Nextcloud / CalDAV", "read & write, app password", setup_caldav),
    ("ics", "Any .ics link", "read only: Proton, Outlook, Google secret address", setup_ics),
    ("local", "Local calendar", "offline, stays on this machine", setup_local),
]


def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    saved = False
    print("Chronica setup: connect a calendar\n")
    try:
        if arg == "reconnect":
            entries = reconnect_google()
        else:
            match = [p for p in PROVIDERS if p[0] == arg]
            if not match:
                for i, (_, title, detail, _) in enumerate(PROVIDERS, 1):
                    print(f"  {i}  {title:<20} {detail}")
                choice = parse_pick(input("\nWhich one? ").strip() or "x", len(PROVIDERS))
                if not choice or len(choice) != 1:
                    print("Nothing chosen.")
                    return 1
                match = [PROVIDERS[choice[0]]]
            entries = match[0][3]()
        if entries:
            save(entries)
            saved = True
        print("Syncing...")
        fe.sync_all_events()
        print("\nDone. Your calendar panel will update in a moment.")
        return 0
    except (KeyboardInterrupt, EOFError):
        # A Google sign-in may already be stored; only the calendar list is known untouched.
        print("\nCancelled." if saved else "\nCancelled, no calendars were added.")
        return 1
    except Exception as exc:
        print(f"\nSetup failed: {exc}")
        print(f"Help for each step: {GUIDE}")
        return 1


if __name__ == "__main__":
    code = main()
    if sys.stdin.isatty():
        try:
            input("\nPress Enter to close.")
        except (KeyboardInterrupt, EOFError):
            pass
    sys.exit(code)
