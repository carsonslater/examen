"""Tests for the examen CLI: argument parsing, boilerplate filtering, and search."""

import os
import sqlite3
from datetime import datetime

import pytest

import examen

FIXED_NOW = datetime(2026, 10, 3, 10, 13)


def render_template(**overrides):
    """Renders the entry template the same way the CLI does."""
    fields = {
        "date_str": "Saturday, October 03, 2026",
        "time_str": "10:13 AM",
        "default_title": "Entry for 2026-10-03",
    }
    fields.update(overrides)
    return examen.TEMPLATE.format(**fields)


# A complete entry containing no user-written text at all.
TEMPLATE_ONLY_ENTRY = render_template()

# The same entry with real prose added under one of the prompts.
ENTRY_WITH_CONTENT = examen.TEMPLATE.replace(
    "## What happened today?\n",
    "## What happened today?\n\nWired money and rewired the search flag.\n",
).format(
    date_str="Saturday, October 03, 2026",
    time_str="10:13 AM",
    default_title="Entry for 2026-10-03",
)


class FixedDatetime(datetime):
    """A datetime whose now() is pinned, for deterministic file names."""

    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Points the module at a throwaway entries dir and database."""
    entries = tmp_path / "entries"
    monkeypatch.setattr(examen, "JOURNAL_DIR", str(entries))
    monkeypatch.setattr(examen, "DB_NAME", str(tmp_path / "index.db"))
    # Never launch a real editor.
    monkeypatch.setattr(examen, "open_file_in_editor", lambda filepath: None)
    return entries


def write_entry(entries, relative_path, content):
    path = entries / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def indexed_filepaths():
    with sqlite3.connect(examen.DB_NAME) as conn:
        return {row[0] for row in conn.execute("SELECT filepath FROM journal_files")}


def no_prompt(monkeypatch, answer=""):
    """Stubs the interactive prompt that search_entries uses."""
    monkeypatch.setattr("builtins.input", lambda *args: answer)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_no_args_creates_a_new_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(examen, "create_and_open_entry", lambda: calls.append("create"))

    assert examen.main([]) == 0
    assert calls == ["create"]


def test_sync_flag_runs_sync_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(examen, "sync_files_to_sql", lambda: None)

    assert examen.main(["--sync"]) == 0
    assert "Sync complete" in capsys.readouterr().out


def test_search_flag_passes_the_term_through(monkeypatch):
    seen = []
    monkeypatch.setattr(examen, "search_entries", lambda query: seen.append(query))

    assert examen.main(["--search", "wire"]) == 0
    assert seen == ["wire"]


def test_search_without_a_term_is_an_error_and_creates_nothing(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(examen, "search_entries", lambda query: calls.append(query))
    monkeypatch.setattr(examen, "create_and_open_entry", lambda: calls.append("create"))

    assert examen.main(["--search"]) == 1
    assert calls == []
    assert "Usage" in capsys.readouterr().out


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_search_with_a_blank_term_is_an_error(monkeypatch, blank):
    calls = []
    monkeypatch.setattr(examen, "search_entries", lambda query: calls.append(query))

    assert examen.main(["--search", blank]) == 1
    assert calls == []


@pytest.mark.parametrize("flag", ["--srch", "--Search", "-s", "--help"])
def test_unknown_flag_errors_instead_of_creating_an_entry(monkeypatch, capsys, flag):
    calls = []
    monkeypatch.setattr(examen, "create_and_open_entry", lambda: calls.append("create"))

    assert examen.main([flag]) == 1
    assert calls == []
    assert "Unknown option" in capsys.readouterr().out


def test_main_reads_sys_argv_when_called_without_arguments(monkeypatch):
    monkeypatch.setattr(examen.sys, "argv", ["examen.py", "--sync"])
    monkeypatch.setattr(examen, "sync_files_to_sql", lambda: None)

    assert examen.main() == 0


# ---------------------------------------------------------------------------
# Boilerplate filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "# Opening Prayer",
        "># Psalm 131 (ESV)",
        "### A Song of Ascents. Of David.",
        "# Questions about the last 24-48 hours of your life.",
        "## What happened today?",
        "- [ ] Glad",
        "- [ ] Hurt",
        "> **1** O Lord, my heart is not lifted up;",
    ],
)
def test_template_lines_are_boilerplate(line):
    assert examen._is_boilerplate(line)


@pytest.mark.parametrize(
    "line",
    [
        "# Saturday, October 03, 2026 - 10:13 AM",
        "Title: Entry for 2026-10-03",
        "# Monday, January 05, 2026 - 07:04 AM",
    ],
)
def test_rendered_placeholder_lines_are_boilerplate(line):
    """Header fields vary per entry but are still template output."""
    assert examen._is_boilerplate(line)


@pytest.mark.parametrize(
    "line",
    [
        "Wired money and rewired the search flag.",
        "## What happened today? I fixed the bug.",
        "I am grateful for a quiet evening.",
    ],
)
def test_user_written_lines_are_not_boilerplate(line):
    assert not examen._is_boilerplate(line)


def test_snippet_is_empty_when_only_the_template_matches():
    assert examen._matching_snippet(TEMPLATE_ONLY_ENTRY, "Psalm") == ""
    assert examen._matching_snippet(TEMPLATE_ONLY_ENTRY, "gratitude") == ""


def test_snippet_returns_user_content_and_is_case_insensitive():
    assert (
        examen._matching_snippet(ENTRY_WITH_CONTENT, "wire")
        == "Wired money and rewired the search flag."
    )
    assert examen._matching_snippet(ENTRY_WITH_CONTENT, "WIRE") == (
        "Wired money and rewired the search flag."
    )


def test_snippet_caps_the_number_of_matched_lines():
    content = "\n".join(f"wire line {n}" for n in range(5))
    assert examen._matching_snippet(content, "wire", max_lines=2) == (
        "wire line 0 | wire line 1"
    )


# ---------------------------------------------------------------------------
# Search behavior
# ---------------------------------------------------------------------------


def test_search_reports_matches_outside_the_template(journal, monkeypatch, capsys):
    write_entry(journal, "202610/2026-10-03_10-13.md", ENTRY_WITH_CONTENT)
    no_prompt(monkeypatch)

    examen.search_entries("wire")

    out = capsys.readouterr().out
    assert "Found 1 entry" in out
    assert "2026-10-03_10-13.md" in out
    assert "Wired money and rewired the search flag." in out


def test_search_ignores_entries_matching_only_the_template(journal, monkeypatch, capsys):
    write_entry(journal, "202610/2026-10-03_10-13.md", TEMPLATE_ONLY_ENTRY)
    no_prompt(monkeypatch)

    examen.search_entries("Psalm")

    assert "No entries found" in capsys.readouterr().out


def test_search_still_matches_on_filename(journal, monkeypatch, capsys):
    """A filename hit counts even when the body only matches the template."""
    write_entry(journal, "202610/2026-10-03_wire.md", TEMPLATE_ONLY_ENTRY)
    no_prompt(monkeypatch)

    examen.search_entries("wire")

    assert "2026-10-03_wire.md" in capsys.readouterr().out


def test_search_opens_the_chosen_entry(journal, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(examen, "open_file_in_editor", opened.append)
    write_entry(journal, "202610/first.md", "the wire is here")
    no_prompt(monkeypatch, "1")

    examen.search_entries("wire")

    assert len(opened) == 1
    assert opened[0].endswith(os.path.join("202610", "first.md"))


@pytest.mark.parametrize("answer", ["0", "9", "abc"])
def test_search_rejects_an_invalid_selection(journal, monkeypatch, capsys, answer):
    opened = []
    monkeypatch.setattr(examen, "open_file_in_editor", opened.append)
    write_entry(journal, "202610/first.md", "the wire is here")
    no_prompt(monkeypatch, answer)

    examen.search_entries("wire")

    assert opened == []
    assert "Invalid selection" in capsys.readouterr().out


def test_search_cancels_on_empty_selection(journal, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(examen, "open_file_in_editor", opened.append)
    write_entry(journal, "202610/first.md", "the wire is here")
    no_prompt(monkeypatch, "")

    examen.search_entries("wire")

    assert opened == []
    assert "Cancelled." in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Month folders and indexing
# ---------------------------------------------------------------------------


def test_create_entry_lands_in_a_month_folder(journal, monkeypatch, capsys):
    monkeypatch.setattr(examen, "datetime", FixedDatetime)

    examen.create_and_open_entry()

    assert (journal / "202610" / "2026-10-03_10-13.md").exists()
    assert "202610" in capsys.readouterr().out


def test_month_dir_derives_the_folder_name(journal):
    assert examen.month_dir(datetime(2026, 1, 9)) == os.path.join(
        str(journal), "202601"
    )
    assert examen.month_dir(datetime(2026, 12, 31)) == os.path.join(
        str(journal), "202612"
    )


def test_sync_indexes_entries_nested_in_month_folders(journal):
    write_entry(journal, "202610/2026-10-03_10-13.md", "october")
    write_entry(journal, "202609/2026-09-01_08-00.md", "september")

    examen.sync_files_to_sql()

    assert indexed_filepaths() == {
        os.path.join(examen.JOURNAL_DIR, "202610", "2026-10-03_10-13.md"),
        os.path.join(examen.JOURNAL_DIR, "202609", "2026-09-01_08-00.md"),
    }


def test_sync_still_indexes_a_flat_entries_dir(journal):
    """The previous layout keeps working."""
    write_entry(journal, "2026-09-01_08-00.md", "older entry")

    examen.sync_files_to_sql()

    assert indexed_filepaths() == {
        os.path.join(examen.JOURNAL_DIR, "2026-09-01_08-00.md")
    }


def test_sync_drops_rows_for_deleted_files(journal):
    path = write_entry(journal, "202610/2026-10-03_10-13.md", "october")
    examen.sync_files_to_sql()
    assert len(indexed_filepaths()) == 1

    path.unlink()
    examen.sync_files_to_sql()

    assert indexed_filepaths() == set()


def test_sync_ignores_non_markdown_files(journal):
    write_entry(journal, "202610/notes.txt", "text entry")
    write_entry(journal, "202610/entry.md", "markdown entry")
    write_entry(journal, "202610/image.png", "not an entry")

    examen.sync_files_to_sql()

    assert indexed_filepaths() == {
        os.path.join(examen.JOURNAL_DIR, "202610", "notes.txt"),
        os.path.join(examen.JOURNAL_DIR, "202610", "entry.md"),
    }
