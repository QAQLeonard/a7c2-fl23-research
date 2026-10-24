"""Offline ownership model for the AP query -> reply -> quiescence path.

This model does not call UIPC, allocate a message, inspect a packet, or touch a
camera.  It is the host-side state contract around the existing one-shot
components.  An accepted handoff keeps the outer context alive; only an
independently observed quiescence fence can close it.
"""

from dataclasses import dataclass
from enum import Enum, auto


class SessionPhase(Enum):
    IDLE = auto()
    HANDED_OFF = auto()
    REPLY_RELEASED = auto()
    COMPLETE = auto()
    UNKNOWN = auto()


@dataclass
class QuerySession:
    nonce: int
    own_id: int
    phase: SessionPhase = SessionPhase.IDLE
    message: int | None = None
    poll_attempts: int = 0
    reply_attempts: int = 0
    fence_generation: int | None = None

    def _fail(self) -> None:
        self.phase = SessionPhase.UNKNOWN

    def handoff(self, *, nonce: int, own_id: int, message: int) -> None:
        """Record a known transport handoff; the caller must keep its context."""
        if (self.phase is not SessionPhase.IDLE or nonce != self.nonce
                or own_id != self.own_id or not isinstance(message, int)
                or message <= 0):
            self._fail()
            raise ValueError("invalid or reused query handoff")
        self.message = message
        self.phase = SessionPhase.HANDED_OFF

    def poll(self, *, status: int, message: int | None = None) -> bool:
        """Consume one poll result. Empty is pending; errors become UNKNOWN."""
        if self.phase is not SessionPhase.HANDED_OFF or self.poll_attempts:
            self._fail()
            raise ValueError("poll is not a fresh operation")
        self.poll_attempts = 1
        if status == -1022 and message in (None, 0):
            return False
        if status or not isinstance(message, int) or message <= 0:
            self._fail()
            raise ValueError("poll ownership is unknown")
        self.message = message
        return True

    def reply(self, *, matched: bool, release_status: int) -> None:
        """Record an inspected/released reply without claiming remote quiescence."""
        if self.phase is not SessionPhase.HANDED_OFF or not self.poll_attempts:
            self._fail()
            raise ValueError("reply has no owned poll result")
        self.reply_attempts += 1
        if release_status or not matched:
            self._fail()
            raise ValueError("reply ownership or protocol is unresolved")
        self.phase = SessionPhase.REPLY_RELEASED

    def fence(self, *, generation: int, observed: bool) -> None:
        """Close only after a separately observed same-generation quiet fence."""
        if (self.phase is not SessionPhase.REPLY_RELEASED or not observed
                or not isinstance(generation, int) or generation <= 0):
            self._fail()
            raise ValueError("quiescence fence is not independently proven")
        self.fence_generation = generation
        self.phase = SessionPhase.COMPLETE

    def can_close(self) -> bool:
        return self.phase is SessionPhase.COMPLETE
