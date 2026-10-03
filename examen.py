# /// script
# requires-python = ">=3.11"
# ///

import os
import re
import subprocess
import sys
import sqlite3
from datetime import datetime

DB_NAME = "journal_index.db"
JOURNAL_DIR = "entries"

# Customize your Markdown template here
TEMPLATE = """# {date_str} - {time_str}
Title: {default_title}
Tags: #examen

# Opening Prayer

># Psalm 131 (ESV)

### A Song of Ascents. Of David.

> **1** O Lord, my heart is not lifted up;
> my eyes are not raised too high;
> I do not occupy myself with things
> too great and too marvelous for me.
>
> **2** But I have calmed and quieted my soul,
> like a weaned child with its mother;
> like a weaned child is my soul within me.
>
> **3** O Israel, hope in the Lord
> from this time forth and forevermore.

# Questions about the last 24-48 hours of your life.

## What happened today?


## For what moment am I most grateful?


## When did I give and recieve the most love?


## What was most life-giving?


## What was most life-thwarting


## When did I have the deepest sense of connection with God, others and myself?


## When did I have the least sense of connection with God, others and myself?


## Where was I aware of living out of the fruit of the Spirit? Where was there an absence of the fruit of the Spirit?


## Where did I experience "desolation"? Where did I find "consolation"?


## Check the boxes for emotions that you're feeling right now:

- [ ] Glad
- [ ] Sad
- [ ] Anger
- [ ] Guilt
- [ ] Lonely
- [ ] Fear
- [ ] Shame
- [ ] Hurt


## What common themes did you discover as you reflected on the last 24-48 hours?


## What habits and patterns do you want to continue to see in your life? What habits and patterns do you want to change or stop?


## Write a simple, one-sentence prayer of gratitude to God for his consistent presence in your life.

-
"""


def initialize_system():
    """Ensures the storage folder and SQLite index database exist."""
    if not os.path.exists(JOURNAL_DIR):
        os.makedirs(JOURNAL_DIR)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS journal_files (
                filepath TEXT PRIMARY KEY,
                last_modified REAL,
                filename TEXT,
                content TEXT
            )
        """)
        conn.commit()


def sync_files_to_sql():
    """Scans the entries directory and syncs text files into SQLite."""
    initialize_system()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        current_files = []

        for filename in os.listdir(JOURNAL_DIR):
            if filename.endswith((".txt", ".md")):
                filepath = os.path.join(JOURNAL_DIR, filename)
                current_files.append(filepath)

                mtime = os.path.getmtime(filepath)

                # Check if file needs an index update
                cursor.execute(
                    "SELECT last_modified FROM journal_files WHERE filepath = ?",
                    (filepath,),
                )
                row = cursor.fetchone()

                if row is None or row[0] < mtime:
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()

                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO journal_files (filepath, last_modified, filename, content)
                            VALUES (?, ?, ?, ?)
                        """,
                            (filepath, mtime, filename, content),
                        )
                    except Exception as e:
                        print(f"⚠️ Error reading {filename}: {e}")

        # Clean up database records for files deleted manually from disk
        cursor.execute("SELECT filepath FROM journal_files")
        db_files = [row[0] for row in cursor.fetchall()]
        for db_file in db_files:
            if db_file not in current_files:
                cursor.execute(
                    "DELETE FROM journal_files WHERE filepath = ?", (db_file,)
                )

        conn.commit()


def open_file_in_editor(filepath):
    """Cross-platform command to open the file in the system's default text editor."""
    if sys.platform == "win32":
        os.startfile(filepath)
    elif sys.platform == "darwin":  # macOS
        subprocess.run(["open", filepath])
    else:  # Linux
        subprocess.run(["xdg-open", filepath])


# Placeholder fields render differently in every entry, so they become wildcards
# when deciding whether a matching line is part of the generated template.
_TEMPLATE_PLACEHOLDERS = ("{date_str}", "{time_str}", "{default_title}")
_PLACEHOLDER_SENTINEL = "\x00"


def _build_template_line_patterns():
    """Compiles a regex for each non-empty line of the entry template.

    Lines containing placeholder fields are treated as wildcards so rendered
    headers (date, time, title) still count as boilerplate.
    """
    patterns = []
    for line in TEMPLATE.splitlines():
        if not line.strip():
            continue
        normalized = line
        for placeholder in _TEMPLATE_PLACEHOLDERS:
            normalized = normalized.replace(placeholder, _PLACEHOLDER_SENTINEL)
        escaped = re.escape(normalized).replace(re.escape(_PLACEHOLDER_SENTINEL), ".*")
        patterns.append(re.compile(f"^{escaped}$"))
    return patterns


TEMPLATE_LINE_PATTERNS = _build_template_line_patterns()


def _is_boilerplate(line):
    """True if the line comes from the generated entry template."""
    return any(pattern.match(line) for pattern in TEMPLATE_LINE_PATTERNS)


def _matching_snippet(content, query, max_lines=3):
    """Preview of the query's matching lines, ignoring boilerplate template lines."""
    query_lower = query.lower()
    matched = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and query_lower in line.lower() and not _is_boilerplate(line)
    ]
    return " | ".join(matched[:max_lines])


def search_entries(query):
    """Searches indexed entry content/filenames and opens a chosen match."""
    sync_files_to_sql()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        like = f"%{query}%"
        cursor.execute(
            """
            SELECT filepath, filename, content
            FROM journal_files
            WHERE content LIKE ? OR filename LIKE ?
            ORDER BY filename DESC
            """,
            (like, like),
        )
        rows = cursor.fetchall()

    query_lower = query.lower()
    matches = []
    for filepath, filename, content in rows:
        snippet = _matching_snippet(content, query)
        # A hit inside the boilerplate template alone isn't a real match.
        if snippet or query_lower in filename.lower():
            matches.append((filepath, filename, snippet))

    if not matches:
        print(f"🔍 No entries found matching '{query}' outside the entry template.")
        return

    count = len(matches)
    print(f"🔍 Found {count} entr{'y' if count == 1 else 'ies'} matching '{query}':\n")
    for i, (_, filename, snippet) in enumerate(matches, start=1):
        print(f"  [{i}] {filename}")
        if snippet:
            print(f"      {snippet}")

    choice = input("\nOpen which entry? (number, or Enter to cancel): ").strip()
    if not choice:
        print("Cancelled.")
        return
    if not choice.isdigit() or not 1 <= int(choice) <= count:
        print(f"⚠️ Invalid selection: '{choice}'.")
        return

    filepath = matches[int(choice) - 1][0]
    print(f"📖 Opening: {filepath}")
    open_file_in_editor(filepath)


def create_and_open_entry():
    """Generates a new text file from the template and opens it."""
    initialize_system()

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M")

    # Create a unique, descriptive file name
    filename = f"{date_str}_{time_str}.md"
    filepath = os.path.join(JOURNAL_DIR, filename)

    # Only write file if it doesn't already exist to prevent accidental overwrites
    if not os.path.exists(filepath):
        formatted_template = TEMPLATE.format(
            date_str=now.strftime("%A, %B %d, %Y"),
            time_str=now.strftime("%I:%M %p"),
            default_title=f"Entry for {date_str}",
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_template)
        print(f"📝 Created new journal entry: {filepath}")
    else:
        print(f"📖 Opening existing entry: {filepath}")

    # Open file for editing immediately
    open_file_in_editor(filepath)

    # Run a background sync to pick up the newly created template
    sync_files_to_sql()


if __name__ == "__main__":
    # If arguments are passed, we handle utility features like syncing
    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        print("🔄 Running manual journal synchronization...")
        sync_files_to_sql()
        print("✅ Sync complete.")
    elif len(sys.argv) > 1 and sys.argv[1] == "--search":
        if len(sys.argv) < 3 or not sys.argv[2].strip():
            print('⚠️ Usage: examen.py --search "your search term"')
            sys.exit(1)
        search_entries(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        print(f"⚠️ Unknown option: {sys.argv[1]}")
        print('Usage: examen.py [--sync | --search "term"]')
        sys.exit(1)
    else:
        # Default behavior: generate file and open editor
        create_and_open_entry()
