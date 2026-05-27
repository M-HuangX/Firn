"""Tests for retrain_pipeline.py — retrain schedule computation and KB helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.retrain_pipeline import (
    RetrainEpoch,
    RetrainSchedule,
    reset_firn,
    compute_schedule,
    print_schedule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTICLE_TEMPLATE = """\
---
slug: {slug}
source: test
tier: 2
content_type: news
title: {title}
published_date: {published_date}
---
{body}"""

_ARTICLE_NO_DATE_TEMPLATE = """\
---
slug: {slug}
source: test
tier: 2
content_type: news
title: {title}
---
{body}"""


def _seed_article(
    kb: KnowledgeBase,
    slug: str,
    published_date: str | None = None,
    title: str | None = None,
    body: str = "Article body content here.",
    *,
    unread: bool = True,
) -> None:
    """Write an article into library/unread/ or library/read/."""
    if title is None:
        title = f"Article {slug}"
    if published_date is not None:
        content = _ARTICLE_TEMPLATE.format(
            slug=slug, title=title, published_date=published_date, body=body,
        )
    else:
        content = _ARTICLE_NO_DATE_TEMPLATE.format(
            slug=slug, title=title, body=body,
        )
    subdir = "unread" if unread else "read"
    target_dir = kb.root / "library" / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{slug}.md").write_text(content, encoding="utf-8")


@pytest.fixture
def kb(tmp_path):
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    return _kb


# ---------------------------------------------------------------------------
# compute_schedule tests
# ---------------------------------------------------------------------------


def test_compute_schedule_empty_library(kb):
    """KB has no articles -> returns empty schedule."""
    schedule = compute_schedule(kb)
    assert schedule.epochs == []
    assert schedule.total_articles == 0
    assert schedule.total_chars == 0
    assert schedule.date_range == ("", "")


def test_compute_schedule_from_unread(kb):
    """Articles in unread/ are included in the schedule."""
    dates = ["2026-03-10", "2026-03-11", "2026-03-12"]
    for i, date in enumerate(dates):
        _seed_article(kb, f"art-{i}", published_date=date, unread=True)

    schedule = compute_schedule(kb, min_articles=3)

    assert schedule.total_articles == 3
    assert len(schedule.epochs) >= 1
    all_slugs = []
    for epoch in schedule.epochs:
        all_slugs.extend(epoch.article_slugs)
    assert sorted(all_slugs) == ["art-0", "art-1", "art-2"]


def test_compute_schedule_from_read(kb):
    """Articles in read/ are also included in the schedule."""
    _seed_article(kb, "read-1", published_date="2026-04-01", unread=False)
    _seed_article(kb, "read-2", published_date="2026-04-02", unread=False)
    _seed_article(kb, "read-3", published_date="2026-04-03", unread=False)

    schedule = compute_schedule(kb, min_articles=3)

    assert schedule.total_articles == 3
    all_slugs = [s for e in schedule.epochs for s in e.article_slugs]
    assert sorted(all_slugs) == ["read-1", "read-2", "read-3"]


def test_compute_schedule_mixed_read_unread(kb):
    """Schedule includes articles from BOTH read/ and unread/."""
    _seed_article(kb, "old-1", published_date="2026-03-10", unread=False)
    _seed_article(kb, "old-2", published_date="2026-03-11", unread=False)
    _seed_article(kb, "new-1", published_date="2026-03-12", unread=True)
    _seed_article(kb, "new-2", published_date="2026-03-13", unread=True)

    schedule = compute_schedule(kb, min_articles=3)

    assert schedule.total_articles == 4
    all_slugs = [s for e in schedule.epochs for s in e.article_slugs]
    assert sorted(all_slugs) == ["new-1", "new-2", "old-1", "old-2"]
    assert schedule.date_range == ("2026-03-10", "2026-03-13")


def test_compute_schedule_basic_grouping(kb):
    """Seed 8 articles across 4 dates (2 per day), min_articles=3."""
    dates = ["2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"]
    for i, date in enumerate(dates):
        _seed_article(kb, f"art-{i * 2}", published_date=date)
        _seed_article(kb, f"art-{i * 2 + 1}", published_date=date)

    schedule = compute_schedule(kb, min_articles=3)

    assert schedule.total_articles == 8
    assert len(schedule.epochs) >= 1

    all_slugs = []
    for epoch in schedule.epochs:
        all_slugs.extend(epoch.article_slugs)
    assert sorted(all_slugs) == sorted([f"art-{i}" for i in range(8)])

    for epoch in schedule.epochs:
        assert epoch.simulated_date == epoch.covers_dates[-1]

    for epoch in schedule.epochs[:-1]:
        assert epoch.article_count >= 3

    assert schedule.date_range == ("2026-03-10", "2026-03-13")


def test_compute_schedule_sparse_dates_aggregation(kb):
    """Articles on close dates get merged until min_articles is met."""
    dates = ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"]
    for i, date in enumerate(dates):
        _seed_article(kb, f"sparse-{i}", published_date=date)

    schedule = compute_schedule(kb, min_articles=3, max_gap_days=7)

    assert schedule.total_articles == 5
    assert len(schedule.epochs) == 2
    assert schedule.epochs[0].article_count == 3
    assert schedule.epochs[0].covers_dates == ["2026-04-01", "2026-04-02", "2026-04-03"]
    assert schedule.epochs[0].simulated_date == "2026-04-03"
    assert schedule.epochs[1].article_count == 2
    assert schedule.epochs[1].covers_dates == ["2026-04-04", "2026-04-05"]
    assert schedule.epochs[1].simulated_date == "2026-04-05"


def test_compute_schedule_gap_forces_split(kb):
    """Two clusters separated by > max_gap_days -> forced into separate epochs."""
    _seed_article(kb, "early-1", published_date="2026-01-10")
    _seed_article(kb, "early-2", published_date="2026-01-11")
    _seed_article(kb, "late-1", published_date="2026-03-15")
    _seed_article(kb, "late-2", published_date="2026-03-16")

    schedule = compute_schedule(kb, min_articles=5, max_gap_days=7)

    assert len(schedule.epochs) == 2
    assert schedule.epochs[0].article_count == 2
    assert "early-1" in schedule.epochs[0].article_slugs
    assert "early-2" in schedule.epochs[0].article_slugs
    assert schedule.epochs[1].article_count == 2
    assert "late-1" in schedule.epochs[1].article_slugs
    assert "late-2" in schedule.epochs[1].article_slugs


def test_compute_schedule_single_day_many_articles(kb):
    """One day with 10 articles -> one epoch."""
    for i in range(10):
        _seed_article(kb, f"same-day-{i}", published_date="2026-06-01")

    schedule = compute_schedule(kb, min_articles=3)

    assert len(schedule.epochs) == 1
    assert schedule.epochs[0].article_count == 10
    assert schedule.epochs[0].simulated_date == "2026-06-01"
    assert schedule.epochs[0].covers_dates == ["2026-06-01"]
    assert schedule.date_range == ("2026-06-01", "2026-06-01")


def test_compute_schedule_unknown_dates(kb):
    """Some articles have no published_date -> appended to last epoch."""
    _seed_article(kb, "dated-1", published_date="2026-05-01")
    _seed_article(kb, "dated-2", published_date="2026-05-02")
    _seed_article(kb, "dated-3", published_date="2026-05-03")
    _seed_article(kb, "unknown-1", published_date=None)
    _seed_article(kb, "unknown-2", published_date=None)

    schedule = compute_schedule(kb, min_articles=10)

    assert schedule.total_articles == 5
    last_epoch = schedule.epochs[-1]
    assert "unknown-1" in last_epoch.article_slugs
    assert "unknown-2" in last_epoch.article_slugs
    assert schedule.date_range == ("2026-05-01", "2026-05-03")


def test_compute_schedule_all_unknown_dates(kb):
    """ALL articles have no published_date -> single epoch with today's date."""
    _seed_article(kb, "no-date-1", published_date=None)
    _seed_article(kb, "no-date-2", published_date=None)
    _seed_article(kb, "no-date-3", published_date=None)

    schedule = compute_schedule(kb, min_articles=2)

    assert len(schedule.epochs) == 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert schedule.epochs[0].simulated_date == today
    assert schedule.epochs[0].article_count == 3
    assert schedule.epochs[0].covers_dates == []
    assert schedule.date_range == (today, today)


def test_compute_schedule_custom_params(kb):
    """Custom min_articles=5, max_gap_days=2."""
    dates = [
        "2026-02-01", "2026-02-02", "2026-02-03",
        "2026-02-04", "2026-02-05", "2026-02-06",
    ]
    for i, date in enumerate(dates):
        _seed_article(kb, f"custom-{i}", published_date=date)

    schedule = compute_schedule(kb, min_articles=5, max_gap_days=2)

    assert len(schedule.epochs) == 2
    assert schedule.epochs[0].article_count == 5
    assert schedule.epochs[1].article_count == 1

    # Test gap-forced split
    kb2_path = kb.root.parent / "kb2"
    kb2 = KnowledgeBase(kb_root=kb2_path)
    kb2.ensure_structure()

    _seed_article(kb2, "c1", published_date="2026-02-01")
    _seed_article(kb2, "c2", published_date="2026-02-02")
    _seed_article(kb2, "c3", published_date="2026-02-06")  # 4-day gap
    _seed_article(kb2, "c4", published_date="2026-02-07")

    schedule2 = compute_schedule(kb2, min_articles=5, max_gap_days=2)

    assert len(schedule2.epochs) == 2
    assert schedule2.epochs[0].article_count == 2
    assert schedule2.epochs[1].article_count == 2


# ---------------------------------------------------------------------------
# list_all_library tests
# ---------------------------------------------------------------------------


def test_list_all_library_empty(kb):
    assert kb.list_all_library() == []


def test_list_all_library_mixed(kb):
    _seed_article(kb, "unread-a", published_date="2026-01-01", unread=True)
    _seed_article(kb, "read-b", published_date="2026-01-02", unread=False)

    result = kb.list_all_library()
    assert sorted(result) == ["read-b", "unread-a"]


def test_list_all_library_dedup(kb):
    """If same slug exists in both (shouldn't happen), it's still one entry."""
    _seed_article(kb, "dup", published_date="2026-01-01", unread=True)
    _seed_article(kb, "dup", published_date="2026-01-01", unread=False)

    result = kb.list_all_library()
    assert result == ["dup"]


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_reset_firn(tmp_path):
    """Verify reset_firn backs up and clears notebook, library, archive, logs."""
    # Use project_root layout so logs_dir = root.parent / "logs" works
    project_root = tmp_path / "project"
    project_root.mkdir()
    kb = KnowledgeBase(project_root=project_root)
    kb.ensure_structure()
    obj_dir = kb.root / "notebook"

    # Create notebook content
    themes_dir = obj_dir / "themes"
    themes_dir.mkdir(parents=True, exist_ok=True)
    (themes_dir / "ai-capex.md").write_text("# AI Capex\nContent", encoding="utf-8")
    (obj_dir / "core_mind.md").write_text("# Core Mind\nState", encoding="utf-8")
    (obj_dir / "latest_report.md").write_text("# Report", encoding="utf-8")

    for subdir in ["events", "sectors", "stocks", "core_mind_history"]:
        d = obj_dir / subdir
        d.mkdir(parents=True, exist_ok=True)
        (d / "test-item.md").write_text(f"# {subdir} content", encoding="utf-8")

    # Create library content
    for subdir in ["unread", "read"]:
        d = kb.root / "library" / subdir
        d.mkdir(parents=True, exist_ok=True)
        (d / "article.md").write_text("---\ntitle: test\n---\nbody", encoding="utf-8")

    # Create archive content
    archive_dir = kb.root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "old.md").write_text("archived", encoding="utf-8")

    # Create logs
    logs_dir = kb.root.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_exec = logs_dir / "20260101_000000_abc"
    log_exec.mkdir()
    (log_exec / "execution_info.json").write_text("{}", encoding="utf-8")

    # Preserve config/principles
    config_dir = obj_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text("key: value", encoding="utf-8")

    backup_dir = reset_firn(kb)

    # Verify backup exists
    assert backup_dir.is_dir()
    assert (backup_dir / "notebook" / "themes" / "ai-capex.md").is_file()
    assert (backup_dir / "notebook" / "core_mind.md").is_file()
    assert (backup_dir / "library" / "unread" / "article.md").is_file()
    assert (backup_dir / "archive" / "old.md").is_file()
    assert (backup_dir / "logs" / "20260101_000000_abc" / "execution_info.json").is_file()

    # Verify notebook cleared
    for subdir in ["themes", "events", "sectors", "stocks", "core_mind_history"]:
        d = obj_dir / subdir
        assert d.is_dir(), f"{subdir} dir should still exist"
        assert list(d.iterdir()) == [], f"{subdir} should be empty"
    assert not (obj_dir / "core_mind.md").exists()
    assert not (obj_dir / "latest_report.md").exists()

    # Verify library cleared (but dirs remain)
    assert (kb.root / "library" / "unread").is_dir()
    assert (kb.root / "library" / "read").is_dir()
    unread_files = [f for f in (kb.root / "library" / "unread").iterdir() if f.name != ".gitkeep"]
    assert unread_files == []

    # Verify archive cleared
    assert list(archive_dir.iterdir()) == []

    # Verify logs cleared (empty dir recreated)
    assert logs_dir.is_dir()
    assert list(logs_dir.iterdir()) == []

    # Verify config preserved
    assert (config_dir / "settings.yaml").is_file()


# ---------------------------------------------------------------------------
# print_schedule test
# ---------------------------------------------------------------------------


def test_print_schedule(capsys):
    """Verify print_schedule output format."""
    schedule = RetrainSchedule(
        epochs=[
            RetrainEpoch(
                epoch_num=1,
                simulated_date="2026-03-10",
                covers_dates=["2026-03-08", "2026-03-09", "2026-03-10"],
                article_slugs=["a1", "a2", "a3"],
                article_count=3,
                total_chars=5000,
            ),
            RetrainEpoch(
                epoch_num=2,
                simulated_date="2026-03-15",
                covers_dates=["2026-03-15"],
                article_slugs=["a4", "a5"],
                article_count=2,
                total_chars=3000,
            ),
            RetrainEpoch(
                epoch_num=3,
                simulated_date="2026-04-01",
                covers_dates=[],
                article_slugs=["a6"],
                article_count=1,
                total_chars=1500,
            ),
        ],
        total_articles=6,
        total_chars=9500,
        date_range=("2026-03-08", "2026-04-01"),
    )

    print_schedule(schedule)
    captured = capsys.readouterr().out

    assert "Retrain Schedule" in captured
    assert "2026-03-08 -> 2026-04-01" in captured
    assert "6 articles in 3 epochs" in captured
    assert "9,500" in captured
    assert "Epoch" in captured
    assert "Simulated Date" in captured
    assert "2026-03-10" in captured
    assert "2026-03-15" in captured
    assert "2026-04-01" in captured
    assert "2026-03-08..2026-03-10" in captured
    assert "unknown" in captured
