"""Defensive system-clock guard shared by all four connector scripts.

Why: connector windows are computed as `datetime.now(timezone.utc) - timedelta(days=30 * N)`.
If the system clock is wrong (sandbox time-freeze, NTP failure, drifted VM), the
window silently shifts and the retrieval returns papers from the wrong date range.
This module hard-fails on implausible clock readings and warns on suspicious ones.

The novelty-skill orchestrator (../novelty-skill/scripts/run.py) also runs an
identical guard upstream, so this is defense-in-depth: even if a connector script
is invoked directly (not via the orchestrator), the clock check still fires.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone


def assert_sane_now() -> datetime:
    now = datetime.now(timezone.utc)
    floor = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ceiling = datetime(2027, 1, 1, tzinfo=timezone.utc)
    if now < floor:
        raise RuntimeError(
            f'System clock returns {now.isoformat()}, which is before 2024-01-01. '
            f'Sandbox time-freeze, NTP failure, or wrong TZ suspected. '
            f'Connector windows are runtime-relative; window arithmetic is corrupted. '
            f'Set TZ correctly before retrying.'
        )
    if now > ceiling:
        print(f'WARNING: system clock returns {now.isoformat()}; '
              f'window arithmetic will use this. Verify intentional.', file=sys.stderr)
    return now
