"""Defensive system-clock guard shared by all four connector scripts.

Why: connector windows are computed as `datetime.now(timezone.utc) - timedelta(days=30 * N)`.
If the system clock is wrong (sandbox time-freeze, NTP failure, drifted VM), the
window silently shifts and the retrieval returns papers from the wrong date range.
This module hard-fails on implausible clock readings and warns on suspicious ones.

The idea-spark orchestrator (../idea_spark/scripts/run.py) also runs an
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


def resolve_now(as_of: str | None = None) -> datetime:
    """Resolve the reference 'now' used for connector window arithmetic.

    The real system clock is ALWAYS validated first (assert_sane_now) so a frozen /
    drifted sandbox clock still hard-fails. When `as_of` (YYYY-MM-DD) is supplied,
    the returned reference date is backdated to it instead of the real now — this is
    how forward-prediction evals reconstruct the literature state "as of" a past
    submission date (e.g. retrieve only papers a researcher could have seen before a
    target paper was published). The backdate is validated against two bounds:
    it must be on/after 2015-01-01 (pre-2015 ML preprint coverage is too sparse for
    the windows to be meaningful) and on/before the real now (you cannot retrieve the
    future). An out-of-range or unparseable `as_of` raises rather than silently
    falling back, because a silently-wrong reference date corrupts every window.
    """
    real_now = assert_sane_now()
    if not as_of:
        return real_now
    try:
        ref = datetime.strptime(as_of.strip(), '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise RuntimeError(f'--as-of must be YYYY-MM-DD, got {as_of!r}: {e}') from e
    floor = datetime(2015, 1, 1, tzinfo=timezone.utc)
    if ref < floor:
        raise RuntimeError(
            f'--as-of {as_of} is before 2015-01-01; ML preprint coverage that far '
            f'back is too sparse for the retrieval windows to be meaningful.'
        )
    if ref > real_now:
        raise RuntimeError(
            f'--as-of {as_of} is in the future relative to the real clock '
            f'({real_now.date().isoformat()}); cannot retrieve papers that do not exist yet.'
        )
    print(f'[time-guard] backdating retrieval reference date to {ref.date().isoformat()} '
          f'(real clock: {real_now.date().isoformat()})', file=sys.stderr)
    return ref
