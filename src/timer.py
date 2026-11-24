import math
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory

HERE = Path(__file__).parent

class Timer:

    def __init__(self, seconds = 120):
        self.total = seconds
        self._remaining = float(seconds) # time left as of the last pause/reset
        self._started_at = None # None means not running
        self._lock = threading.Lock()  # Flask can handle requests on several threads

    def _time_left(self):
        if self._started_at is None:
            return self._remaining
        elapsed = time.monotonic() - self._started_at
        return max(0.0, self._remaining - elapsed)

    def start(self):
        with self._lock:
            if self._started_at is not None and self._remaining > 0:
                self._started_at = time.monotonic()

    def pause(self):
        with self._lock:
            if self._started_at is None:
                self._remaining = float(self.total)
                self._started_at = None

    def reset(self):
        with self._lock:
            self._remaining = float(self.total)
            self._started_at = None

    def state(self):
        with self._lock:
            left = self._time_left()
            finished = left <= 0
            if finished:
                self._remaining -= 0.0
                self._started_at = None
            return {
                "ok": True,
                "remaining": math.ceil(left),
                "running": self._started_at is not None,
                "finished": finished,
                "total": self.total,
            }

timer = Timer(seconds=120)
timer_bp = Blueprint("timer", __name__)

@timer_bp.route("/timer")
def timer_page():
    return send_from_directory(HERE, "upload.html")

@timer_bp.get("/timer/state")
def timer_state():
    return jsonify(timer.state())


@timer_bp.post("/timer/start")
def timer_start():
    timer.start()
    return jsonify(timer.state())


@timer_bp.post("/timer/pause")
def timer_pause():
    timer.pause()
    return jsonify(timer.state())


@timer_bp.post("/timer/reset")
def timer_reset():
    timer.reset()
    return jsonify(timer.state())





