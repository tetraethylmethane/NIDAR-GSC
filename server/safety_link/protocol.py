"""868 MHz safety-link protocol — abort and recall.

Rules 8.19 and MB §8 require mission abort and emergency recall, and they are
two of only four operator actions permitted at all. Today `/api/safety/abort`
sets a boolean that nothing reads. This is the wire format that makes it real.

THE THREE CONSTRAINTS THIS IS BUILT TO
--------------------------------------
**1. It must not share the mesh.** The reason to abort is frequently that the
mesh has failed. An abort path over the failed link is not an abort path. This
runs on the separate 865–867 MHz radio (BOM tab 01 rows 41–42), which exists for
exactly this and nothing else.

**2. Framed, sequenced, acknowledged per aircraft.** LoRa is lossy and slow, so
a single unacknowledged packet is not a command — it is a hope. Frames are short
and CRC-checked, repeated for several seconds, and each aircraft acknowledges by
system id so the operator can see *which* aircraft accepted. "I pressed abort"
and "all three aircraft are returning" are different statements.

**3. It must survive a hung companion.** This protocol is the *secondary* path.
The primary is the safety receiver driving an RC channel straight into the
flight controller — `RC7_OPTION=4` (RTL) in the parameter file — which works
with no software of ours in the loop. If the companion has hung, and a hung
companion is one of the reasons to abort, the RC path still recovers the
aircraft. This layer adds addressing, acknowledgement and an audit trail.

WIRE FORMAT (11 bytes; a LoRa payload at SF7 carries this comfortably)

    0      magic 0xA5
    1      version 0x01
    2      command
    3      target system id, 0 = broadcast to the whole fleet
    4-5    sequence, big-endian, wraps at 65535
    6-9    epoch seconds, big-endian
    10-11  CRC-16/CCITT-FALSE over bytes 0..9

Short on purpose: airtime at SF7/125 kHz is roughly 60 ms for this frame, so it
can be repeated at 2 Hz for ten seconds and still leave the band almost idle.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from enum import IntEnum

MAGIC = 0xA5
VERSION = 0x01
FRAME_LEN = 12
BROADCAST = 0


class Command(IntEnum):
    """Deliberately tiny. Anything else belongs on the mesh, not here."""

    ABORT = 0x01        # hold, then sequenced recovery
    RECALL = 0x02       # immediate return to launch
    ACK = 0x10          # aircraft -> GCS
    HEARTBEAT = 0x20    # link liveness, so a dead radio is visible BEFORE it
    #                     is needed


class ProtocolError(ValueError):
    pass


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE. Chosen over a checksum because a stuck-high bit on a
    noisy radio is exactly the failure a sum will not catch."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    command: Command
    target: int = BROADCAST
    seq: int = 0
    t: int = 0

    def encode(self) -> bytes:
        if not 0 <= self.target <= 255:
            raise ProtocolError("target must fit in one byte")
        body = struct.pack(">BBBBHI", MAGIC, VERSION, int(self.command),
                           self.target, self.seq & 0xFFFF,
                           int(self.t or time.time()) & 0xFFFFFFFF)
        return body + struct.pack(">H", crc16(body))


def decode(data: bytes) -> Frame:
    """Parse a frame. Raises ProtocolError on anything suspect.

    Every rejection here is a real radio failure mode: truncation from a partial
    receive, a flipped bit from noise, a stale frame replayed by a repeater, or
    another system on a shared band.
    """
    if len(data) != FRAME_LEN:
        raise ProtocolError(f"expected {FRAME_LEN} bytes, got {len(data)}")
    magic, ver, cmd, target, seq, t = struct.unpack(">BBBBHI", data[:10])
    if magic != MAGIC:
        raise ProtocolError("bad magic — not our traffic")
    if ver != VERSION:
        raise ProtocolError(f"unsupported version {ver}")
    got = struct.unpack(">H", data[10:12])[0]
    want = crc16(data[:10])
    if got != want:
        raise ProtocolError(f"CRC mismatch: {got:#06x} != {want:#06x}")
    try:
        command = Command(cmd)
    except ValueError:
        raise ProtocolError(f"unknown command {cmd:#04x}") from None
    return Frame(command=command, target=target, seq=seq, t=t)


class Sender:
    """GCS side. Repeats a command until every aircraft has acknowledged."""

    def __init__(self, drone_ids=(1, 2, 3), repeat_s: float = 10.0,
                 interval_s: float = 0.5) -> None:
        self.drone_ids = tuple(drone_ids)
        self.repeat_s = repeat_s
        self.interval_s = interval_s
        self._seq = 0
        self.pending: Command | None = None
        self.acked: set[int] = set()
        self.started_at: float | None = None

    def begin(self, command: Command, now: float | None = None) -> bytes:
        """Start a command. Returns the first frame to transmit."""
        if command not in (Command.ABORT, Command.RECALL):
            raise ProtocolError("only ABORT and RECALL may be sent")
        self._seq = (self._seq + 1) & 0xFFFF
        self.pending = command
        self.acked = set()
        self.started_at = now if now is not None else time.time()
        return Frame(command, BROADCAST, self._seq, int(self.started_at)).encode()

    def frame(self, now: float | None = None) -> bytes | None:
        """The next repeat, or None once every aircraft has acknowledged."""
        if self.pending is None or self.complete:
            return None
        now = now if now is not None else time.time()
        if now - (self.started_at or now) > self.repeat_s:
            return None
        return Frame(self.pending, BROADCAST, self._seq, int(now)).encode()

    def on_receive(self, data: bytes) -> int | None:
        """Handle an inbound frame. Returns the acknowledging system id."""
        try:
            f = decode(data)
        except ProtocolError:
            return None
        if f.command is not Command.ACK or f.seq != self._seq:
            return None
        if f.target in self.drone_ids:
            self.acked.add(f.target)
            return f.target
        return None

    @property
    def complete(self) -> bool:
        return bool(self.pending) and set(self.drone_ids) <= self.acked

    @property
    def missing(self) -> tuple[int, ...]:
        """Aircraft that have NOT acknowledged. This is what the operator must
        see: 'abort sent' is not the same as 'abort received'."""
        return tuple(d for d in self.drone_ids if d not in self.acked)


class Receiver:
    """Aircraft side. Deduplicates repeats and acknowledges."""

    def __init__(self, drone_id: int, max_age_s: float = 30.0) -> None:
        self.drone_id = drone_id
        self.max_age_s = max_age_s
        self.last_seq: int | None = None
        self.action: Command | None = None
        self.rejected = 0

    def on_receive(self, data: bytes, now: float | None = None):
        """Returns (action, ack_bytes) — action is None if nothing to do."""
        now = now if now is not None else time.time()
        try:
            f = decode(data)
        except ProtocolError:
            self.rejected += 1
            return None, None

        if f.command not in (Command.ABORT, Command.RECALL):
            return None, None
        if f.target not in (BROADCAST, self.drone_id):
            return None, None

        # Reject stale frames. A repeater or a delayed packet must not trigger
        # an abort minutes after the operator cleared it.
        if abs(now - f.t) > self.max_age_s:
            self.rejected += 1
            return None, None

        ack = Frame(Command.ACK, self.drone_id, f.seq, int(now)).encode()

        if f.seq == self.last_seq:
            # A repeat of a command already acted on. Acknowledge again --
            # the earlier ack may have been the packet that was lost -- but do
            # not re-trigger the action.
            return None, ack

        self.last_seq = f.seq
        self.action = f.command
        return f.command, ack
