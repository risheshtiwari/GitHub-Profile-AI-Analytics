"""Phase 4 — Contribution Analytics.

Consumes GitHub's /repos/{owner}/{repo}/stats/commit_activity payload, aggregated
across every analyzed repo for a developer:
  [{ "week": <unix ts, Sunday 00:00 UTC>, "total": int, "days": [int x 7] }, ...]
"""

from collections import defaultdict
from datetime import datetime, timedelta

WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def merge_weekly_activity(per_repo_weeks: list[list[dict]]) -> dict[int, dict]:
    """Merge multiple repos' weekly activity into one timeline keyed by week unix ts."""
    merged: dict[int, dict] = defaultdict(lambda: {"total": 0, "days": [0] * 7})
    for weeks in per_repo_weeks:
        for w in weeks:
            week_ts = w.get("week")
            if week_ts is None:
                continue
            merged[week_ts]["total"] += w.get("total", 0)
            days = w.get("days", [0] * 7)
            for i in range(7):
                merged[week_ts]["days"][i] += days[i] if i < len(days) else 0
    return dict(merged)


def commits_per_week_series(merged: dict[int, dict]) -> list[dict]:
    series = [
        {"week_start": datetime.utcfromtimestamp(ts).date().isoformat(), "count": data["total"]}
        for ts, data in sorted(merged.items())
    ]
    return series


def commits_per_month(merged: dict[int, dict]) -> dict[str, int]:
    buckets: dict[str, int] = defaultdict(int)
    for ts, data in merged.items():
        dt = datetime.utcfromtimestamp(ts)
        key = f"{dt.year}-{dt.month:02d}"
        buckets[key] += data["total"]
    return dict(sorted(buckets.items()))


def longest_streak_weeks(merged: dict[int, dict]) -> int:
    weeks_sorted = sorted(merged.items())
    longest = current = 0
    for _, data in weeks_sorted:
        if data["total"] > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def most_active_weekday(merged: dict[int, dict]) -> str | None:
    totals = [0] * 7
    for data in merged.values():
        for i in range(7):
            totals[i] += data["days"][i]
    if sum(totals) == 0:
        return None
    idx = totals.index(max(totals))
    return WEEKDAY_NAMES[idx]


def average_commits_per_week(merged: dict[int, dict]) -> float:
    if not merged:
        return 0.0
    total = sum(d["total"] for d in merged.values())
    return round(total / len(merged), 2)


def inactive_periods(merged: dict[int, dict], min_gap_weeks: int = 3) -> list[dict]:
    """Return contiguous runs of >= min_gap_weeks with zero commits."""
    weeks_sorted = sorted(merged.items())
    periods = []
    gap_start = None
    gap_len = 0
    for ts, data in weeks_sorted:
        if data["total"] == 0:
            if gap_start is None:
                gap_start = ts
            gap_len += 1
        else:
            if gap_start is not None and gap_len >= min_gap_weeks:
                periods.append({
                    "start": datetime.utcfromtimestamp(gap_start).date().isoformat(),
                    "weeks": gap_len,
                })
            gap_start = None
            gap_len = 0
    if gap_start is not None and gap_len >= min_gap_weeks:
        periods.append({
            "start": datetime.utcfromtimestamp(gap_start).date().isoformat(),
            "weeks": gap_len,
        })
    return periods
