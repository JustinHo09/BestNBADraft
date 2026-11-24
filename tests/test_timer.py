import unittest


"""Tests for draft_timer.py (the DraftTimer class and its Flask routes).

Run from the project folder with:  pytest -v

The tests swap the module's clock for a fake one, so they run instantly and never
depend on real seconds passing.
"""

import threading
import pytest
from flask import Flask

import timer
from timer import Timer

class FakeClock:
    """Stands in for the time module so each test controls exactly how much time passes."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(timer, "time", fake)
    return fake


# ---------------------------------------------------------------- Timer class


class TestTimer:
    def test_starts_full_and_stopped(self, clock):
        state = Timer(120).state()
        assert state["ok"] is True
        assert state["remaining"] == 120
        assert state["total"] == 120
        assert state["running"] is False
        assert state["finished"] is False

    def test_does_not_count_down_until_started(self, clock):
        timer = Timer(120)
        clock.advance(60)
        assert timer.state()["remaining"] == 120
        assert timer.state()["running"] is False

    def test_counts_down_after_start(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(30)
        state = timer.state()
        assert state["running"] is True
        assert state["remaining"] == 90

    def test_remaining_rounds_up_to_whole_seconds(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(0.5)
        assert timer.state()["remaining"] == 120   # 119.5 shows as 120
        clock.advance(0.5)
        assert timer.state()["remaining"] == 119   # exactly 119.0
        clock.advance(0.2)
        assert timer.state()["remaining"] == 119   # 118.8 shows as 119

    def test_pause_freezes_the_time(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(30)
        timer.pause()
        clock.advance(500)
        state = timer.state()
        assert state["running"] is False
        assert state["remaining"] == 90
        assert state["finished"] is False

    def test_resume_continues_from_where_it_paused(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(30)
        timer.pause()
        clock.advance(100)       # time passing while paused must not count
        timer.start()
        clock.advance(10)
        assert timer.state()["remaining"] == 80

    def test_multiple_pause_resume_cycles_add_up(self, clock):
        timer = Timer(120)
        for _ in range(4):
            timer.start()
            clock.advance(10)
            timer.pause()
            clock.advance(25)
        assert timer.state()["remaining"] == 80

    def test_pause_when_not_running_changes_nothing(self, clock):
        timer = Timer(120)
        timer.pause()
        clock.advance(10)
        state = timer.state()
        assert state["remaining"] == 120
        assert state["running"] is False

    def test_starting_twice_does_not_restart_the_countdown(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(30)
        timer.start()            # second click while already running
        clock.advance(30)
        assert timer.state()["remaining"] == 60

    def test_reset_restores_full_time_and_stops(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(45)
        timer.reset()
        clock.advance(10)        # must stay stopped after the reset
        state = timer.state()
        assert state["remaining"] == 120
        assert state["running"] is False

    def test_reset_while_paused(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(45)
        timer.pause()
        timer.reset()
        assert timer.state()["remaining"] == 120

    def test_reaches_zero_and_reports_finished(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(120)
        state = timer.state()
        assert state["remaining"] == 0
        assert state["finished"] is True
        assert state["running"] is False

    def test_stays_at_zero_long_after_finishing(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(10_000)
        state = timer.state()
        assert state["remaining"] == 0     # never negative
        assert state["finished"] is True

    def test_cannot_start_once_finished(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(200)
        timer.state()                      # lets the timer notice it finished
        timer.start()
        assert timer.state()["running"] is False

    def test_reset_after_finishing_allows_a_new_run(self, clock):
        timer = Timer(120)
        timer.start()
        clock.advance(200)
        timer.state()
        timer.reset()
        timer.start()
        clock.advance(5)
        state = timer.state()
        assert state["finished"] is False
        assert state["remaining"] == 115

    def test_custom_length(self, clock):
        timer = Timer(seconds=5)
        assert timer.state()["total"] == 5
        timer.start()
        clock.advance(5)
        assert timer.state()["finished"] is True

    def test_zero_second_timer_is_already_finished_and_cannot_start(self, clock):
        timer = Timer(seconds=0)
        timer.start()
        state = timer.state()
        assert state["finished"] is True
        assert state["running"] is False

    def test_survives_calls_from_many_threads(self, clock):
        timer = Timer(120)
        errors = []

        def hammer():
            try:
                for _ in range(200):
                    timer.start()
                    timer.state()
                    timer.pause()
                    timer.reset()
            except Exception as exc:       # any exception here is a failure
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert timer.state()["remaining"] in range(0, 121)


# ---------------------------------------------------------------- Flask routes


@pytest.fixture
def client(clock, monkeypatch):
    # Fresh timer per test so tests can't affect each other through the module-level one.
    monkeypatch.setattr(timer, "timer", Timer(120))
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(timer.timer_bp)
    return app.test_client()


class TestTimerRoutes:
    def test_initial_state(self, client):
        data = client.get("/timer/state").get_json()
        assert data == {"ok": True, "remaining": 120, "running": False, "finished": False, "total": 120}

    def test_start_begins_the_countdown(self, client, clock):
        data = client.post("/timer/start").get_json()
        assert data["running"] is True
        clock.advance(10)
        assert client.get("/timer/state").get_json()["remaining"] == 110

    def test_pause_freezes_the_countdown(self, client, clock):
        client.post("/timer/start")
        clock.advance(10)
        data = client.post("/timer/pause").get_json()
        assert data["running"] is False
        assert data["remaining"] == 110
        clock.advance(50)
        assert client.get("/timer/state").get_json()["remaining"] == 110

    def test_reset_returns_to_full_time(self, client, clock):
        client.post("/timer/start")
        clock.advance(10)
        data = client.post("/timer/reset").get_json()
        assert data["remaining"] == 120
        assert data["running"] is False

    def test_reports_finished_when_time_is_up(self, client, clock):
        client.post("/timer/start")
        clock.advance(121)
        data = client.get("/timer/state").get_json()
        assert data["finished"] is True
        assert data["remaining"] == 0

    def test_all_browsers_share_one_timer(self, client, clock):
        other_browser = client.application.test_client()
        client.post("/timer/start")
        clock.advance(20)
        assert other_browser.get("/timer/state").get_json()["remaining"] == 100

    def test_state_changing_routes_reject_get(self, client):
        for path in ("/timer/start", "/timer/pause", "/timer/reset"):
            assert client.get(path).status_code == 405

    def test_state_route_rejects_post(self, client):
        assert client.post("/timer/state").status_code == 405

    def test_timer_page_is_served(self, client):
        resp = client.get("/timer")
        try:
            assert resp.status_code == 200
            assert b"<html" in resp.data
        finally:
            resp.close()