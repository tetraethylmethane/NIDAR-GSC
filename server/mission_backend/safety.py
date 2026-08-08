"""Abort and recall — the GCS end of the 868 MHz safety link.

Until now `/api/safety/abort` set a boolean that nothing read, returned 200 and
a green tick, and the aircraft kept flying. This connects it to the wire format
in `safety_link/protocol.py`.

WHAT THIS DOES AND DOES NOT GUARANTEE
-------------------------------------
It transmits framed, sequenced commands on the safety radio and collects
per-aircraft acknowledgements, so the operator can see **which** aircraft
accepted. "Abort sent" and "abort received" are different claims and only the
second one matters.

It is the **secondary** abort path. The primary is the safety receiver driving
`RC7_OPTION=4` (RTL) straight into the flight controller, which works with a
hung companion — and a hung companion is one of the reasons to abort. Nothing
here should be relied on as the only way to recover an aircraft.

**If no radio is attached the state is `NO_RADIO`, not `SENT`.** A safety
control that reports success when it did nothing is worse than no control at
all, because it stops the operator reaching for the transmitter.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any

from safety_link.protocol import Command, Sender

log = logging.getLogger("groundstation.safety")

# Repeat for ten seconds at 2 Hz. LoRa is lossy; a single frame is a hope.
REPEAT_S = 10.0
INTERVAL_S = 0.5


class SafetyLink:
    """Transmits abort/recall and tracks who has acknowledged."""

    def __init__(self, drone_ids=(1, 2, 3), host: str | None = None,
                 port: int = 14570, rx_port: int = 14571) -> None:
        self.drone_ids = tuple(drone_ids)
        self.host = host                     # None -> no radio configured
        self.port = port
        self.rx_port = rx_port

        self.sender = Sender(drone_ids, repeat_s=REPEAT_S,
                             interval_s=INTERVAL_S)
        self._lock = threading.Lock()
        self._tx: threading.Thread | None = None
        self._rx: threading.Thread | None = None
        self._stop = threading.Event()
        self._sock: socket.socket | None = None

        self.last_command: str | None = None
        self.last_started: float | None = None
        self.frames_sent = 0

    # ------------------------------------------------------------- status
    @property
    def configured(self) -> bool:
        """False when no safety radio endpoint is set. The UI must show this."""
        return bool(self.host)

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = self.sender
            if not self.configured:
                state = "NO_RADIO"
            elif s.pending is None:
                state = "IDLE"
            elif s.complete:
                state = "ACKNOWLEDGED"
            elif self.last_started and time.time() - self.last_started > REPEAT_S:
                state = "TIMEOUT"
            else:
                state = "SENDING"
            return {
                "state": state,
                "configured": self.configured,
                "command": self.last_command,
                "acknowledged": sorted(s.acked),
                "missing": list(s.missing) if s.pending else [],
                "drones": list(self.drone_ids),
                "frames_sent": self.frames_sent,
                "elapsed_s": (round(time.time() - self.last_started, 1)
                              if self.last_started else None),
            }

    # ------------------------------------------------------------ transmit
    def trigger(self, command: Command) -> dict[str, Any]:
        """Begin an abort or recall. Returns the status immediately."""
        with self._lock:
            self.last_command = command.name
            self.last_started = time.time()
            first = self.sender.begin(command, now=self.last_started)

        if not self.configured:
            log.error(
                "%s requested but NO SAFETY RADIO IS CONFIGURED — nothing was "
                "transmitted. Use the safety pilot's transmitter.", command.name
            )
            return self.status()

        log.warning("%s transmitting on the safety link", command.name)
        self._send(first)
        self._start_threads()
        return self.status()

    def _send(self, data: bytes) -> None:
        try:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._sock.sendto(data, (self.host, self.port))
            self.frames_sent += 1
        except OSError:
            log.exception("safety-link transmit failed")
            try:
                if self._sock:
                    self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _tx_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                frame = self.sender.frame()
            if frame is None:
                return
            self._send(frame)
            self._stop.wait(INTERVAL_S)

    def _rx_loop(self) -> None:
        try:
            rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rx.bind(("0.0.0.0", self.rx_port))
            rx.settimeout(1.0)
        except OSError:
            log.exception("cannot bind the safety-link receive port")
            return
        try:
            while not self._stop.is_set():
                try:
                    data, _ = rx.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    return
                with self._lock:
                    who = self.sender.on_receive(data)
                if who is not None:
                    log.warning("drone %d acknowledged %s", who,
                                self.last_command)
        finally:
            try:
                rx.close()
            except OSError:
                pass

    def _start_threads(self) -> None:
        if self._tx is None or not self._tx.is_alive():
            self._stop.clear()
            self._tx = threading.Thread(target=self._tx_loop, daemon=True,
                                        name="safety-tx")
            self._tx.start()
        if self._rx is None or not self._rx.is_alive():
            self._rx = threading.Thread(target=self._rx_loop, daemon=True,
                                        name="safety-rx")
            self._rx.start()

    def stop(self) -> None:
        self._stop.set()
        for t in (self._tx, self._rx):
            if t:
                t.join(timeout=2.0)
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
