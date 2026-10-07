# examen

A small command-line tool for daily **Examen** journaling. It creates a
timestamped Markdown entry from a built-in template, opens it in your default
editor, and keeps a SQLite full-text index so you can find past entries later.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

This creates the project virtual environment and resolves the lockfile.

## Usage

Run everything through `uv run`:

```bash
# Create an entry for right now and open it in your default editor
uv run examen.py

# Search existing entries (prompts you to open one of the matches)
uv run examen.py --search "wire"

# Rebuild the SQLite index from the entries/ directory
uv run examen.py --sync
```

With no arguments, `examen.py` generates an entry for the current date and time.
If a file already exists for that timestamp it is opened rather than overwritten.
Unknown options print a usage message and exit instead of silently creating an entry.

### Where entries are stored

Entries are grouped into one folder per month, named `YYYYMM`:

```
entries/202610/2026-10-03_10-13.md
entries/202610/2026-10-21_07-05.md
entries/202611/2026-11-02_21-40.md
```

The indexer walks `entries/` recursively, so a flat layout from an older version
still works.

### How search behaves

- Matching is case-insensitive and covers both the entry text and the filename.
- Text from the entry template itself (prayer, question headings, checkbox list)
  is treated as boilerplate and filtered out, so words that appear in *every*
  entry — e.g. `Psalm`, `gratitude`, `Spirit` — don't match everything.
- Template placeholder fields (date, time, title) are matched as wildcards, so
  rendered header lines also count as boilerplate.
- An entry is only listed if the query appears outside the boilerplate, or in
  the filename. A hit that exists only in the template is reported as no match.
- Each match shows a preview of up to three matching lines.

## Layout

| Path | Purpose |
| --- | --- |
| `examen.py` | The CLI: entry template, indexer, and search. |
| `entries/YYYYMM/` | Your Markdown journal entries, one file per session, grouped by month. |
| `tests/` | Pytest suite for argument parsing, search, and indexing. |
| `journal_index.db` | SQLite index of entry contents, refreshed on each run. Generated locally and gitignored. |

`entries/` and `journal_index.db` are gitignored: both hold the full text of your
journal, so they stay on your machine. Note that earlier commits did include an
entry file and the index; gitignoring only affects future commits, it does not
remove them from history.

## Running the tests

```bash
uv run pytest
```

## Customizing the template

Edit the `TEMPLATE` string near the top of `examen.py`. Because search identifies
boilerplate by exact line match against the current template, changing a template
line after entries exist means the old wording in existing entries will start
counting as real content.
