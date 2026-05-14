"""
RoadLink Gateway — asyncio entry point.

Responsibilities:
  1. Receive UDP BSM packets on :5005
  2. Decode BSM frames via bsm_codec
  3. Maintain VehicleRegistry (spawn/kill OBU nodes)
  4. Run collision engine on every decoded frame
  5. Broadcast JSON payloads over WebSocket :8765
  6. Expose aiohttp REST API on :8080

This is the single orchestrator process. All OBU threads are children.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Set

import aiohttp
import aiohttp.web
import aiohttp_cors  # type: ignore
import websockets
import websockets.server

# ── Resolve imports ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bsm_codec import decode, FRAME_SIZE
from collision_engine.engine import compute_all_pairs
from gateway.registry import VehicleRegistry  # type: ignore

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gateway")

# ── Configuration ────────────────────────────────────────────────────────────
UDP_HOST              = "127.0.0.1"
UDP_PORT              = 5005
WS_HOST               = "127.0.0.1"
WS_PORT               = 8765
REST_HOST             = "127.0.0.1"
REST_PORT             = 8080
WS_HANDSHAKE_TIMEOUT  = 5.0      # seconds to wait for {"type":"dashboard"}


# ── Global state ─────────────────────────────────────────────────────────────
registry       = VehicleRegistry()
ws_clients: Set[websockets.WebSocketServerProtocol] = set()
start_time     = time.monotonic()
collision_matrix: dict = {}


# ═══════════════════════════════════════════════════════════════════════════
#  WebSocket Server
# ═══════════════════════════════════════════════════════════════════════════

async def ws_handler(websocket: websockets.WebSocketServerProtocol) -> None:
    """Handle a single WebSocket client connection."""
    try:
        # Wait for handshake: {"type": "dashboard"}
        raw = await asyncio.wait_for(websocket.recv(), timeout=WS_HANDSHAKE_TIMEOUT)
        msg = json.loads(raw)
        if msg.get("type") != "dashboard":
            await websocket.close(1008, "Invalid handshake")
            return
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
        try:
            await websocket.close(1008, "Handshake timeout")
        except Exception:
            pass
        return

    ws_clients.add(websocket)
    logger.info(f"[WS] Dashboard connected ({len(ws_clients)} clients)")

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "drive_input":
                # { type:"drive_input", id:"<registry_id>", mode:"drive"|"auto",
                #   keys: {w:bool, a:bool, s:bool, d:bool} }
                vid  = msg.get("id", "")
                mode = msg.get("mode", "auto")
                keys = msg.get("keys", {"w": False, "a": False, "s": False, "d": False})
                if vid:
                    registry.set_drive_override(vid, mode, keys)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(websocket)
        logger.info(f"[WS] Dashboard disconnected ({len(ws_clients)} clients)")


async def ws_broadcast(payload: dict) -> None:
    """Broadcast a JSON payload to all connected dashboard clients."""
    if not ws_clients:
        return

    data = json.dumps(payload)
    # Send to all clients, remove any that have disconnected
    stale = set()
    for ws in ws_clients:
        try:
            await ws.send(data)
        except (websockets.exceptions.ConnectionClosed, Exception):
            stale.add(ws)

    ws_clients.difference_update(stale)


# ═══════════════════════════════════════════════════════════════════════════
#  UDP Receiver
# ═══════════════════════════════════════════════════════════════════════════

class UDPProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol — receives BSM frames from OBU nodes."""

    def __init__(self) -> None:
        self.transport = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Called for every incoming UDP datagram."""
        # Schedule processing in the event loop
        asyncio.ensure_future(self._process_frame(data))

    async def _process_frame(self, data: bytes) -> None:
        """Decode BSM frame, update registry, run collision engine, broadcast."""
        global collision_matrix

        decoded = decode(data)
        if decoded is None:
            return  # Bad frame — CRC fail or wrong size, silently drop

        # Get current vehicle states from registry
        vehicles = registry.get_all_states()
        if not vehicles:
            return

        # Run all-pairs collision computation
        collision_matrix = compute_all_pairs(vehicles)

        # Build WebSocket payload
        elapsed = time.monotonic() - start_time
        payload = {
            "t":                round(elapsed, 2),
            "vehicles":         vehicles,
            "collision_matrix": collision_matrix,
        }

        await ws_broadcast(payload)


# ═══════════════════════════════════════════════════════════════════════════
#  REST API (aiohttp)
# ═══════════════════════════════════════════════════════════════════════════

async def handle_spawn(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """POST /api/vehicles — spawn a new OBU node."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return aiohttp.web.json_response(
            {"error": "invalid JSON"}, status=400
        )

    vtype = body.get("type", "")
    name  = body.get("name", "")

    try:
        result = registry.spawn(name=name, vehicle_type=vtype)
    except ValueError as e:
        msg = str(e)
        status = 409 if "already exists" in msg else 400
        return aiohttp.web.json_response({"error": msg}, status=status)

    logger.info(f"[REST] Spawned: {result['name']} ({result['type']})")
    return aiohttp.web.json_response(result, status=201)


async def handle_list(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /api/vehicles — list all running vehicles."""
    vehicles = registry.list_vehicles()
    return aiohttp.web.json_response({
        "vehicles": vehicles,
        "count":    len(vehicles),
    })


async def handle_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """DELETE /api/vehicles/{id} — kill a vehicle."""
    vid = request.match_info["id"]
    result = registry.kill(vid)

    if result is None:
        return aiohttp.web.json_response(
            {"error": "not found"}, status=404
        )

    logger.info(f"[REST] Deleted: {result['name']}")
    return aiohttp.web.json_response(result)


async def handle_health(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """GET /api/health — gateway health check."""
    return aiohttp.web.json_response({
        "status":     "ok",
        "vehicles":   registry.count,
        "ws_clients": len(ws_clients),
        "uptime_s":   round(time.monotonic() - start_time, 1),
    })


def create_rest_app() -> aiohttp.web.Application:
    """Create and configure the aiohttp REST application."""
    app = aiohttp.web.Application()

    # Routes
    app.router.add_post("/api/vehicles",      handle_spawn)
    app.router.add_get("/api/vehicles",       handle_list)
    app.router.add_delete("/api/vehicles/{id}", handle_delete)
    app.router.add_get("/api/health",         handle_health)

    # CORS — allow the React dashboard (localhost:5173) to access the API
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*",
        )
    })

    # Apply CORS to all routes
    for route in list(app.router.routes()):
        cors.add(route)

    return app


# ═══════════════════════════════════════════════════════════════════════════
#  Main — run all services concurrently
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """Start all gateway services: UDP listener, WebSocket server, REST API."""
    global start_time
    start_time = time.monotonic()

    loop = asyncio.get_running_loop()

    # ── 1. UDP listener ──────────────────────────────────────────────────
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(),
        local_addr=(UDP_HOST, UDP_PORT),
        reuse_port=False,
    )

    # ── 2. WebSocket server ──────────────────────────────────────────────
    ws_server = await websockets.server.serve(
        ws_handler,
        WS_HOST,
        WS_PORT,
    )

    # ── 3. REST API server ───────────────────────────────────────────────
    rest_app    = create_rest_app()
    rest_runner = aiohttp.web.AppRunner(rest_app)
    await rest_runner.setup()
    rest_site = aiohttp.web.TCPSite(rest_runner, REST_HOST, REST_PORT)
    await rest_site.start()

    # ── Banner ───────────────────────────────────────────────────────────
    print()
    print("═══════════════════════════════════════════════════════")
    print("  ROADLINK — Gateway")
    print(f"  UDP  listener  : {UDP_HOST}:{UDP_PORT}")
    print(f"  WebSocket      : ws://{WS_HOST}:{WS_PORT}")
    print(f"  REST API       : http://{REST_HOST}:{REST_PORT}")
    print("  Ctrl+C to stop")
    print("═══════════════════════════════════════════════════════")
    print("[GW] Ready — waiting for OBU connections and dashboard clients...")
    print()

    # ── Run forever (until Ctrl+C) ───────────────────────────────────────
    try:
        await asyncio.Future()  # Block forever
    except asyncio.CancelledError:
        pass
    finally:
        # Graceful shutdown
        logger.info("[GW] Shutting down...")
        registry.shutdown_all()
        transport.close()
        ws_server.close()
        await ws_server.wait_closed()
        await rest_runner.cleanup()
        logger.info("[GW] Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[GW] Interrupted — goodbye.")
