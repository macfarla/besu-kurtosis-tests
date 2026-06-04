#!/usr/bin/env python3
"""
Backpressure regression test for the WebSocket event-loop deadlock fix.

How it works
------------
1. A "slow consumer" thread opens a raw TCP socket, performs a minimal WebSocket
   handshake, sends eth_getLogs, reads a single chunk to confirm Besu started
   responding, then stops calling recv() entirely.  With nothing draining the OS
   receive buffer the TCP window shrinks to zero, Besu's send buffer fills, and
   Vert.x's WebSocket write queue backs up — triggering StreamBackpressure.awaitDrain.

   Why raw socket, not the websockets library?  The websockets library drives IO
   through asyncio, which keeps pumping the kernel receive buffer in the background
   even while the coroutine is suspended in asyncio.sleep().  A blocking OS-level
   socket in its own thread is the only reliable way to stop all reads.

2. While the slow consumer holds the TCP window closed, a probe loop fires
   eth_blockNumber every second on a separate connection for PROBE_DURATION seconds.

3. Pass: every probe returns within PROBE_TIMEOUT — the event loop is free.
   Fail: any probe times out — the event loop is wedged (pre-fix behaviour).

Usage:
    pip install websockets
    python ws_backpressure_test.py \\
        --ws ws://localhost:8546 \\
        --contract 0xABC... \\
        --from-block 100 --to-block 300

For a patched Besu (PR #10354) all probes should pass.
For an unpatched Besu you should see probe timeouts and Vert.x BlockedThreadChecker
warnings in the Besu log within ~2 s of the slow consumer connecting.

Data-size note
--------------
The slow consumer only triggers backpressure once the response exceeds the combined
OS send + receive buffers (~256 KB on Linux, ~256 KB on macOS with default settings).
seed_logs.py with --blocks 200 --per-block 50 produces ~10 000 events (~5 MB of JSON),
which is well above that threshold on both platforms.
"""

import argparse
import asyncio
import base64
import json
import os
import socket
import struct
import sys
import threading
import time
from urllib.parse import urlparse

try:
    import websockets
except ImportError:
    sys.exit("Install websockets:  pip install websockets")


PROBE_TIMEOUT  = 3.0   # seconds — a healthy node replies well within this
PROBE_INTERVAL = 1.0   # seconds between probe calls
PROBE_DURATION = 20.0  # seconds to keep probing while slow consumer is frozen
FREEZE_SECONDS = 25.0  # how long to hold the TCP window closed


# ---------------------------------------------------------------------------
# Raw WebSocket helpers (client-side only, no library dependency)
# ---------------------------------------------------------------------------

def _ws_handshake(sock: socket.socket, host: str, port: int, path: str = "/") -> None:
    """Perform the HTTP → WebSocket upgrade on a connected blocking socket."""
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())

    # Read until we see the end of the HTTP response headers.
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Server closed connection during WS handshake")
        buf += chunk

    if b"101" not in buf:
        raise ConnectionError(f"WebSocket upgrade failed:\n{buf[:500].decode(errors='replace')}")


def _ws_send_text(sock: socket.socket, text: str) -> None:
    """Send a single masked WebSocket text frame (RFC 6455 §5.2)."""
    payload = text.encode()
    length  = len(payload)
    mask    = os.urandom(4)
    masked  = bytes(payload[i] ^ mask[i % 4] for i in range(length))

    header = bytearray()
    header.append(0x81)  # FIN + opcode 1 (text)

    if length < 126:
        header.append(0x80 | length)          # MASK bit + 7-bit length
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))

    header.extend(mask)
    sock.sendall(bytes(header) + masked)


# ---------------------------------------------------------------------------
# Slow consumer: raw blocking socket, stops reading after the first chunk
# ---------------------------------------------------------------------------

def _slow_consumer_thread(
    host: str,
    port: int,
    payload: dict,
    freeze: float,
    ready_event: threading.Event,
) -> None:
    """
    Connect, send eth_getLogs, read one chunk to confirm data is flowing,
    then stop calling recv() for `freeze` seconds so TCP window fills.
    Runs in a daemon thread so it never blocks the main process from exiting.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(15)
        sock.connect((host, port))

        _ws_handshake(sock, host, port)
        _ws_send_text(sock, json.dumps(payload))

        # Read one chunk — proves Besu started sending and fills the local
        # buffer enough that Besu won't time out before we set ready_event.
        sock.recv(65536)

        print(f"[slow-consumer] first chunk received — stopping reads for {freeze}s")
        ready_event.set()

        # Block this thread (not the event loop) — OS receive buffer fills,
        # TCP window drops to zero, Besu's write queue backs up.
        time.sleep(freeze)

        sock.close()
        print("[slow-consumer] socket closed")
    except Exception as exc:
        print(f"[slow-consumer] error: {exc}")
        ready_event.set()  # unblock probe loop so the test can still report


# ---------------------------------------------------------------------------
# Probe loop: fires eth_blockNumber every second on a separate connection
# ---------------------------------------------------------------------------

async def probe_loop(
    ws_url: str,
    duration: float,
    timeout: float,
    interval: float,
    start_event: threading.Event,
) -> bool:
    """Returns True if every probe replied within `timeout`, False otherwise."""

    # Wait (without blocking the event loop) until the slow consumer is ready.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_event.wait)

    print(f"[probe] starting — {duration}s window, {timeout}s timeout per call")

    passed   = True
    deadline = time.monotonic() + duration
    probe_id = 1

    while time.monotonic() < deadline:
        t0 = time.monotonic()
        try:
            async with websockets.connect(ws_url, open_timeout=timeout) as ws:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "method": "eth_blockNumber",
                    "params": [], "id": probe_id,
                }))
                raw     = await asyncio.wait_for(ws.recv(), timeout=timeout)
                elapsed = time.monotonic() - t0
                resp    = json.loads(raw)
                print(f"[probe] #{probe_id:>3}  block={resp.get('result')}  {elapsed*1000:.0f}ms")
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - t0
            print(
                f"[probe] #{probe_id:>3}  TIMEOUT after {elapsed*1000:.0f}ms"
                "  *** EVENT LOOP WEDGED ***"
            )
            passed = False
        except Exception as exc:
            print(f"[probe] #{probe_id:>3}  ERROR: {exc}")
            passed = False

        probe_id += 1
        await asyncio.sleep(interval)

    return passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(args) -> bool:
    parsed = urlparse(args.ws)
    host   = parsed.hostname
    port   = parsed.port or 8546

    get_logs_payload = {
        "jsonrpc": "2.0",
        "method":  "eth_getLogs",
        "params":  [{
            "address":   args.contract,
            "fromBlock": hex(args.from_block),
            "toBlock":   hex(args.to_block),
        }],
        "id": 1,
    }

    ready_event = threading.Event()

    consumer = threading.Thread(
        target=_slow_consumer_thread,
        args=(host, port, get_logs_payload, FREEZE_SECONDS, ready_event),
        daemon=True,
        name="slow-consumer",
    )
    consumer.start()

    passed = await probe_loop(
        args.ws, PROBE_DURATION, PROBE_TIMEOUT, PROBE_INTERVAL, ready_event
    )

    consumer.join(timeout=5)
    return passed


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--ws",         default="ws://localhost:8546")
    ap.add_argument("--contract",   required=True)
    ap.add_argument("--from-block", type=int, required=True)
    ap.add_argument("--to-block",   type=int, required=True)
    args = ap.parse_args()

    print("=" * 60)
    print("WebSocket event-loop backpressure test")
    print(f"  node:     {args.ws}")
    print(f"  range:    blocks {args.from_block}–{args.to_block}")
    print(f"  contract: {args.contract}")
    print("=" * 60)

    passed = asyncio.run(run(args))
    print()

    if passed:
        print("PASS — event loop stayed responsive throughout backpressure window")
        sys.exit(0)
    else:
        print("FAIL — event loop blocked (probe timed out)")
        print("       Check Besu logs for: io.vertx.core.impl.BlockedThreadChecker")
        sys.exit(1)


if __name__ == "__main__":
    main()
