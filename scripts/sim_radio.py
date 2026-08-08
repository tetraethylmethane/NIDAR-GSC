"""Stand-in for the 868 MHz safety radio and the three aircraft on it.

WHAT THIS IS FOR
The abort path was built, unit-tested and honestly reported as unproven,
because with no radio attached `/api/safety/abort` returns 503 NO_RADIO and the
panel shows a red NOT IMPLEMENTED banner. That is the correct behaviour and it
also means **nobody has ever seen the path work**: no frame decoded by a
receiver, no acknowledgement travelling back, no panel turning green.

This closes that without hardware. It binds the UDP port the GCS transmits to,
decodes each frame with the real `safety_link.protocol.Receiver` — the actual
aircraft-side class, not a mock — and sends real ACK frames back. Everything
except the radio itself is the shipping code.

WHAT IT DOES NOT PROVE
Nothing about 868 MHz: not range, not airtime, not the LoRa module, not
interference, not the aerial. Those need the radio and a field. What it proves
is that the framing, sequencing, deduplication, per-aircraft addressing and
acknowledgement logic work end to end against the real GCS.

    python scripts/sim_radio.py                    # all three aircraft ack
    python scripts/sim_radio.py --deaf 2           # drone 2 never acks
    python scripts/sim_radio.py --loss 0.4         # 40 % of frames dropped

`--deaf` is the interesting one. It is what the operator sees when an aircraft
does not accept the abort, which is the case the panel exists to make visible:
"abort sent" and "abort received" are different claims, and only the second
means an aircraft is coming home.

Point the GCS at it with `"safety_radio_host": "127.0.0.1"` in config.json.
"""
from __future__ import annotations

import argparse
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "server"))

from safety_link.protocol import (  # noqa: E402
    Command, ProtocolError, Receiver, decode,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=14570,
                    help="port the GCS transmits to (SafetyLink.port)")
    ap.add_argument("--ack-port", type=int, default=14571,
                    help="port the GCS listens on (SafetyLink.rx_port)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--drones", default="1,2,3")
    ap.add_argument("--deaf", default="",
                    help="comma-separated drone ids that never acknowledge")
    ap.add_argument("--loss", type=float, default=0.0,
                    help="fraction of inbound frames to drop, 0..1")
    args = ap.parse_args()

    ids = [int(x) for x in args.drones.split(",") if x.strip()]
    deaf = {int(x) for x in args.deaf.split(",") if x.strip()}
    receivers = {i: Receiver(i) for i in ids}

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("0.0.0.0", args.port))
    rx.settimeout(1.0)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"safety radio stand-in on udp/{args.port}, acking to "
          f"{args.host}:{args.ack_port}")
    print(f"aircraft: {ids}" + (f"   DEAF: {sorted(deaf)}" if deaf else ""))
    if args.loss:
        print(f"simulated frame loss: {args.loss:.0%}")
    print("waiting for an abort or recall...\n")

    frames = acks = dropped = bad = 0
    try:
        while True:
            try:
                data, _ = rx.recvfrom(256)
            except socket.timeout:
                continue
            frames += 1

            if args.loss and random.random() < args.loss:
                dropped += 1
                continue

            try:
                f = decode(data)
            except ProtocolError as exc:
                bad += 1
                print(f"  REJECTED a frame: {exc}")
                continue

            if f.command not in (Command.ABORT, Command.RECALL):
                continue

            for i in ids:
                action, ack = receivers[i].on_receive(data)
                if action is not None:
                    # This is where an aircraft would act. On the real vehicle
                    # the RC path has already pulled it into RTL; this is the
                    # addressed, acknowledged, audited second path.
                    print(f"  drone {i}: {action.name} seq={f.seq} -> ACTING")
                if ack and i not in deaf:
                    tx.sendto(ack, (args.host, args.ack_port))
                    acks += 1
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nframes received {frames}, acks sent {acks}, "
              f"dropped {dropped}, malformed {bad}")
        rx.close()
        tx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
