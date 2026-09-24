from app.web.ratelimit import LoginLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_an_account_is_locked_after_too_many_failures_from_anywhere_then_unlocks():
    clock = Clock()
    limiter = LoginLimiter(per_account=3, per_address=100, window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.retry_after("1.1.1.1", "Ann@example.com") == 0
        limiter.record_failure("1.1.1.1", "ann@example.com")
        clock.now += 1
    assert limiter.retry_after("2.2.2.2", "ANN@example.com") == 57  # the first failure ages out at 1060
    assert limiter.retry_after("2.2.2.2", "bob@example.com") == 0
    clock.now = 1061
    assert limiter.retry_after("1.1.1.1", "ann@example.com") == 0


def test_one_address_trying_many_accounts_is_locked():
    limiter = LoginLimiter(per_account=100, per_address=2, window_seconds=60, clock=Clock())
    limiter.record_failure("1.1.1.1", "a@example.com")
    limiter.record_failure("1.1.1.1", "b@example.com")
    assert limiter.retry_after("1.1.1.1", "c@example.com") > 0
    assert limiter.retry_after("9.9.9.9", "c@example.com") == 0


def test_signing_in_clears_the_account_count():
    limiter = LoginLimiter(per_account=2, per_address=100, window_seconds=60, clock=Clock())
    limiter.record_failure("1.1.1.1", "a@example.com")
    limiter.clear_account("A@example.com")
    limiter.record_failure("1.1.1.1", "a@example.com")
    assert limiter.retry_after("1.1.1.1", "a@example.com") == 0


def test_guesses_spread_over_many_made_up_accounts_dont_pile_up():
    clock = Clock()
    limiter = LoginLimiter(per_account=3, per_address=10**9, window_seconds=60, clock=clock)
    for i in range(LoginLimiter.MAX_KEYS + 500):
        limiter.record_failure("198.51.100.7", f"nobody{i}@example.com")
    assert len(limiter._failures) <= LoginLimiter.MAX_KEYS + 1
    clock.now += 61  # once the window has passed, a sweep empties it
    limiter.record_failure("198.51.100.8", "someone@example.com")
    for i in range(LoginLimiter.MAX_KEYS):
        limiter.record_failure("198.51.100.8", f"again{i}@example.com")
    assert len(limiter._failures) <= LoginLimiter.MAX_KEYS + 1
    assert all(len(failures) <= 10**9 for failures in limiter._failures.values())
