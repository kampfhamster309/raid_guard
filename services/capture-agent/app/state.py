import threading
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
        self._reconnect_count = 0

    def set(self, capture_state: CaptureState, message: str = "") -> None:
        with self._lock:
            self._capture_state = capture_state
            self._message = message

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
            }


# Module-level singleton shared across app and capture loop
agent_state = AgentState()
