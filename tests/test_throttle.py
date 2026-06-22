"""Unit tests for the AIMD self-healing throttle in src/fetcher.py.

These tests drive the throttle's logic directly (no network) and verify the
behaviours that fix the old death-spiral: bounded slowdown, automatic speed
recovery, capped/escalating-then-resetting cooldowns, and Retry-After parsing.
"""

import time

from src import config, fetcher
from src.fetcher import _parse_retry_after, _Throttle


def _fresh():
    return _Throttle()


def test_starts_at_configured_delay():
    t = _fresh()
    assert t.base_delay == config.REQUEST_DELAY


def test_rate_limit_slows_down_but_is_capped():
    t = _fresh()
    prev = t.base_delay
    for _ in range(50):  # way more than enough to exceed the cap
        t.register_rate_limit(None)
        assert t.base_delay >= prev  # never decreases on a hit
        prev = t.base_delay
    # Multiplicative decrease is bounded by MAX_REQUEST_DELAY (the old bug let
    # this pin at 30s; now it's capped low).
    assert t.base_delay == config.MAX_REQUEST_DELAY
    assert config.MAX_REQUEST_DELAY <= 8.0


def test_success_recovers_speed_after_slowdown():
    t = _fresh()
    t.register_rate_limit(None)
    t.register_rate_limit(None)
    slowed = t.base_delay
    assert slowed > config.REQUEST_DELAY
    # Sustained success must claw the delay back down (the old throttle never
    # did this — recovery is the core fix).
    for _ in range(config.SPEEDUP_AFTER * 5):
        t.register_success()
    assert t.base_delay < slowed


def test_speed_recovery_floors_at_min_delay():
    t = _fresh()
    for _ in range(config.SPEEDUP_AFTER * 100):
        t.register_success()
    assert t.base_delay >= config.MIN_REQUEST_DELAY
    assert abs(t.base_delay - config.MIN_REQUEST_DELAY) < 1e-9


def test_cooldown_is_capped():
    t = _fresh()
    cooldowns = [t.register_rate_limit(None) for _ in range(20)]
    assert max(cooldowns) <= config.MAX_COOLDOWN
    assert config.MAX_COOLDOWN <= 120.0  # no more 15-minute self-imposed sleeps


def test_cooldown_escalation_resets_after_recovery():
    t = _fresh()
    t.register_rate_limit(None)
    escalated = t.register_rate_limit(None)
    assert escalated > config.RATELIMIT_COOLDOWN  # it doubled
    # A clean success streak should reset the escalation back to the base.
    for _ in range(config.SPEEDUP_AFTER):
        t.register_success()
    assert t.register_rate_limit(None) == config.RATELIMIT_COOLDOWN


def test_retry_after_is_honoured_and_capped():
    t = _fresh()
    assert t.register_rate_limit(5.0) == 5.0           # server value honoured
    assert t.register_rate_limit(99999.0) == config.MAX_COOLDOWN  # but capped


def test_parse_retry_after_delta_seconds():
    assert _parse_retry_after("120") == 120.0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("garbage") is None


def test_parse_retry_after_http_date():
    # An HTTP-date a minute in the future should parse to a positive delta.
    future = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 60))
    val = _parse_retry_after(future)
    assert val is not None and 30 < val <= 65


def test_wait_enforces_spacing_between_starts():
    t = _fresh()
    t.base_delay = 0.05
    config_jitter = config.REQUEST_JITTER
    # Two sequential reservations should be spaced by ~base_delay.
    start = time.monotonic()
    t.wait()
    t.wait()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05  # at least one spacing interval enforced
    assert elapsed <= 0.05 + config_jitter + 0.5  # not absurdly long


def test_wait_reserves_distinct_future_slots():
    # Slot reservation must hand out monotonically increasing, distinct slots
    # so concurrent workers don't collide on the same instant.
    t = _fresh()
    t.base_delay = 0.01
    slots = []
    orig_sleep = time.sleep
    try:
        time.sleep = lambda s: None  # don't actually sleep; inspect _next_slot
        for _ in range(5):
            t.wait()
            slots.append(t._next_slot)
    finally:
        time.sleep = orig_sleep
    assert slots == sorted(slots)
    assert len(set(slots)) == len(slots)


# Quietly silence the warning logs the throttle emits during tests.
fetcher.logger.disabled = True
