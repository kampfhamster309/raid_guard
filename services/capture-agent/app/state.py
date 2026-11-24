import threading
import time
from enum import Enum


class CaptureState(str, Enum):
    STARTING = "starting"
    CONNECTING = "connecting"           # authenticating with Fritzbox
    WAITING_FOR_READER = "waiting_for_reader"  # FIFO open, waiting for Suricata
    STREAMING = "streaming"             # data flowing
    RECONNECTING = "reconnecting"       # error, backing off before retry
    ERROR = "error"                     # fatal / unrecoverable


class AgentState:
    """Thread-safe container for capture-agent runtime state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capture_state = CaptureState.STARTING
        self._message = ""
        self._state_since = time.monotonic()
        self._reconnect_count = 0
        # time.monotonic() of the last successful FIFO write; None until the
        # first packet of the current stream has been delivered to Suricata.
        self._last_data_at: float | None = None

    def set(self, capture_state: CaptureState, message: str = "") -> None:
        with self._lock:
            if capture_state != self._capture_state:
                self._state_since = time.monotonic()
            self._capture_state = capture_state
            self._message = message

    def state_age(self) -> float:
        """Seconds since the capture state last changed."""
        with self._lock:
            return time.monotonic() - self._state_since

    def mark_data(self) -> None:
        """Record that pcap bytes were just written to the FIFO."""
        # Plain attribute store (atomic under the GIL) — called once per packet,
        # so avoid taking the lock on the hot path.
        self._last_data_at = time.monotonic()

    def clear_data(self) -> None:
        """Forget the last-data timestamp (new stream about to start)."""
        self._last_data_at = None

    def last_data_age(self) -> float | None:
        """Seconds since the last FIFO write, or None if none yet this stream."""
        last = self._last_data_at
        return None if last is None else time.monotonic() - last

    def increment_reconnects(self) -> None:
        with self._lock:
            self._reconnect_count += 1

    def reset_reconnects(self) -> None:
        with self._lock:
            self._reconnect_count = 0

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "capture_state": self._capture_state.value,
                "message": self._message,
                "reconnect_count": self._reconnect_count,
                "last_data_age_seconds": (
                    None if self._last_data_at is None
                    else round(time.monotonic() - self._last_data_at, 1)
                ),
            }


# Module-level singleton shared across app and capture loop
agent_state = AgentState()
