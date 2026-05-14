# ROADLINK — Multi-Vehicle V2V Simulation Platform

> A game-like, browser-based Vehicle-to-Vehicle (V2V) communication simulator where every vehicle runs its own On-Board Unit (OBU) process, broadcasts a real 28-byte BSM-lite frame over a UDP mesh, and the live React dashboard lets you click any vehicle to inspect its real-time collision risk against every other vehicle on the map.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            YOUR MACHINE                                 │
│                                                                         │
│   OBU-A (thread)  OBU-B (thread)  OBU-C (thread)  OBU-N (thread)        │
│        │               │               │               │                │
│        └───────────────┴───────────────┴───────────────┘                │
│                           UDP :5005 (shared bus)                        │
│                                  │                                      │
│                         Gateway (asyncio)                               │
│                    UDP rx · collision engine · REST                     │
│                         WebSocket :8765                                 │
│                                  │                                      │
│                      React Dashboard :5173                              │
│              Live map · click-to-inspect · spawn/delete                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Table of contents

1. [What this is](#1-what-this-is)
2. [How it works — mental model](#2-how-it-works--mental-model)
3. [Architecture deep-dive](#3-architecture-deep-dive)
4. [BSM-lite frame specification](#4-bsm-lite-frame-specification)
5. [Collision engine](#5-collision-engine)
6. [Project layout](#6-project-layout)
7. [Tech stack](#7-tech-stack)
8. [Prerequisites](#8-prerequisites)
9. [Installation](#9-installation)
10. [Running the simulation](#10-running-the-simulation)
11. [Using the dashboard](#11-using-the-dashboard)
12. [REST API reference](#12-rest-api-reference)
13. [WebSocket payload reference](#13-websocket-payload-reference)
14. [Vehicle types and path profiles](#14-vehicle-types-and-path-profiles)
15. [Alert thresholds](#15-alert-thresholds)
16. [Configuration reference](#16-configuration-reference)
17. [Adding a vehicle programmatically](#17-adding-a-vehicle-programmatically)
18. [Extending — adding a new vehicle type](#18-extending--adding-a-new-vehicle-type)
19. [Troubleshooting](#19-troubleshooting)
20. [Known limitations (MVP)](#20-known-limitations-mvp)
21. [Roadmap](#21-roadmap)

---

## 1. What this is

ROADLINK is a software-only simulation of a Vehicle-to-Vehicle (V2V) communication mesh. No hardware, no GPS chip, no radio — every component is simulated in Python and rendered in a React browser dashboard.

You can spawn as many vehicles as you want at runtime. Each vehicle:

- Runs as an independent Python thread that behaves exactly like an embedded ESP32 OBU firmware would
- Generates a realistic GPS path (random walk with boundary clamping, speed profiles per vehicle type)
- Encodes its state into a **28-byte BSM-lite frame** (with CRC-16 integrity check) every 100–500 ms
- **Broadcasts** that frame over UDP to the shared local bus
- **Receives** frames from every other vehicle on the same bus

The gateway process sits on the UDP bus, maintains a live registry of all known vehicles, runs an all-pairs collision engine on every incoming frame, and pushes the full state + alert matrix to the React dashboard over WebSocket.

In the dashboard you can:

- Watch vehicles move on a real OpenStreetMap tile layer in real time
- Click any vehicle marker to open its prediction dashboard (telemetry, nearby vehicles sorted by TTC, a live TTC/distance chart, event log)
- Spawn a new vehicle (pick type, give it a name) and watch it appear on the map within one frame
- Delete any vehicle and watch it disappear instantly

---

## 2. How it works — mental model

### The OBU (On-Board Unit)

Think of each vehicle as a self-contained embedded device. In real V2V systems the OBU is a small computer mounted in the car that reads GPS, computes its own state, and broadcasts safety messages over DSRC or C-V2X radio. Here we simulate the exact same behavior in software:

```
OBUNode (one Python thread per vehicle)
│
├── path_engine.tick(dt)
│     generates new lat, lon, speed, heading, accel, brake
│
├── bsm_codec.encode(...)
│     packs 28-byte frame with CRC-16
│
├── tx_loop (inner thread)
│     sends UDP datagram to 127.0.0.1:5005 at 2–10 Hz
│
└── rx_loop (inner thread)
      receives UDP datagrams from all other OBUs
      decodes frame, updates local neighbour table
```

### The shared UDP bus

All OBUs send to the same UDP address and port (`127.0.0.1:5005`). The gateway also binds to this port. Because UDP is connectionless and fire-and-forget, every packet sent by any OBU is received by every other listener — this is the P2P broadcast mesh. In a real V2V radio system this is how DSRC broadcast works; we replicate the topology exactly.

### The gateway

The gateway is a single `asyncio` process. It:

1. Listens on UDP `:5005` — decodes every incoming BSM frame
2. Updates the `VehicleRegistry` (a dict mapping `vehicle_id → latest_state`)
3. On every decoded frame runs `compute_all_pairs(registry)` — the collision engine evaluates TTC and CPA for every unique pair of vehicles
4. Builds a JSON payload containing all vehicle states + the full alert matrix
5. Broadcasts that payload over WebSocket to all connected dashboards
6. Exposes an `aiohttp` REST API on `:8080` for spawning and deleting vehicles

### The React dashboard

A standard React 18 SPA. State is held in a Zustand store. A single `useWS` hook owns the WebSocket connection, parses every incoming JSON frame, and dispatches to the store. All components are reactive — map markers move, badges change color, charts extend, the moment a new WS frame arrives.

---

## 3. Architecture deep-dive

### Layer diagram

```
┌──────────────────────────────────────────────────────────────┐
│  OBU LAYER (one thread per vehicle)                          │
│                                                              │
│  OBUNode-A   OBUNode-B   OBUNode-C  ...  OBUNode-N           │
│  car         truck       bike             any type           │
│  PathProfile PathProfile PathProfile      PathProfile        │
│  BSM encode  BSM encode  BSM encode       BSM encode         │
│      │           │           │                │              │
│      └───────────┴───────────┴────────────────┘              │
│                         UDP :5005                            │
└──────────────────────────────┬───────────────────────────────┘
                               │  28-byte BSM frames
┌──────────────────────────────▼───────────────────────────────┐
│  GATEWAY LAYER (single asyncio process)                      │
│                                                              │
│  UDP socket rx ──► BSM decode ──► VehicleRegistry            │
│                                        │                     │
│                              compute_all_pairs()             │
│                              alert matrix (N×N pairs)        │
│                                        │                     │
│  WebSocket :8765 ◄─────────────────────┘                     │
│  aiohttp REST :8080  POST/DELETE /api/vehicles               │
└──────────────────────────────┬───────────────────────────────┘
                               │  JSON over WebSocket
┌──────────────────────────────▼───────────────────────────────┐
│  FRONTEND LAYER (React 18, Vite, port 5173)                  │
│                                                              │
│  useWS hook ──► Zustand vehicleStore                         │
│                      │                                       │
│         ┌────────────┼──────────────┬──────────────┐         │
│         ▼            ▼              ▼              ▼         │
│      MapCanvas  VehicleList   DetailPanel     AlertBar       │
│      Leaflet    sidebar        telemetry +    global         │
│      markers    + SpawnForm    nearby list    worst alert    │
│                                + chart                       │
└──────────────────────────────────────────────────────────────┘
```

### Data flow on a single BSM frame

```
1. OBUNode-A: path_engine.tick(dt)
      → lat=12.9724, lon=77.5941, spd=18.4, hdg=047.2, brake=1

2. OBUNode-A: bsm_codec.encode(...)
      → b'\xaa\xbb\x01\x00\x00\xa0\x01...' (28 bytes, CRC appended)

3. OBUNode-A tx_loop: sock.sendto(frame, ('127.0.0.1', 5005))

4. Gateway UDP rx: data, addr = sock.recvfrom(64)

5. Gateway: decoded = bsm_codec.decode(data)
      → { vehicle_id: 0xA001, lat: 12.9724, lon: 77.5941, ... }

6. Gateway: registry.update('A', decoded)

7. Gateway: matrix = compute_all_pairs(registry)
      → { 'A-B': {ttc:∞, cpa:210, alert:'GREEN'},
          'A-C': {ttc:1.8, cpa:14, alert:'RED'},
          'B-C': {ttc:9.1, cpa:88, alert:'GREEN'} }

8. Gateway: ws_broadcast({ t: 42.1, vehicles: {...}, collision_matrix: {...} })

9. React useWS: setStore(payload)

10. MapCanvas re-renders: Car A marker moves, Bike C pulses red
11. DetailPanel (Car A selected): TTC badge flips RED, chart extends
```

---

## 4. BSM-lite frame specification

Every OBU encodes its state into a fixed-length 28-byte frame before broadcasting.

```
Offset  Bytes  Type    Field           Description
──────  ─────  ──────  ──────────────  ──────────────────────────────────────
0       2      u8[2]   preamble        Always 0xAA 0xBB — frame sync marker
2       1      u8      version         Always 0x01
3       4      u32     vehicle_id      Unique node identifier (big-endian)
7       4      i32     lat_fp          Latitude  × 1e7, degrees (big-endian)
11      4      i32     lon_fp          Longitude × 1e7, degrees (big-endian)
15      2      u16     spd_cms         Speed in cm/s  (metres/s × 100)
17      2      u16     hdg_ddeg        Heading in deci-degrees (degrees × 10)
19      1      i8      accel_b         Acceleration × 10, m/s², clamped ±12.7
20      1      u8      brake           0 = not braking, 1 = braking
21      1      u8      vehicle_cls     0=car, 1=truck, 2=bike, 3=emergency
22      4      u32     timestamp_ms    Milliseconds since node start
26      2      u16     crc16           CRC-16/CCITT-FALSE over bytes [0:26]
```

**CRC-16 algorithm:** CCITT-FALSE, polynomial `0x1021`, initial value `0xFFFF`, no input/output reflection. A frame with a mismatched CRC is silently dropped by the receiver.

**Encoding example:**

```python
frame = encode(
    vehicle_id   = 0xA001,
    lat          = 12.972841,
    lon          = 77.594612,
    speed_mps    = 18.4,
    heading_deg  = 47.2,
    accel_ms2    = -1.2,
    brake        = 1,
    vehicle_class= 0,       # car
    timestamp_ms = 42100,
)
# → 28 bytes, last 2 bytes are CRC-16
```

---

## 5. Collision engine

The collision engine is the single source of truth for all safety math. It is imported by both the gateway (online, real-time) and the test validator (offline).

### Haversine distance

```
haversine_m(lat1, lon1, lat2, lon2) → float (metres)
```

Computes great-circle distance between two GPS coordinates. Used to find the current separation between any two vehicles.

### Time To Collision (TTC)

```
compute_ttc(ego_lat, ego_lon, ego_spd, ego_hdg,
            nb_lat,  nb_lon,  nb_spd,  nb_hdg) → float (seconds)
```

Uses the **closing-velocity method**:

```
TTC = -(r · v_rel) / |v_rel|²

where:
  r      = relative position vector (dx, dy) in metres
  v_rel  = relative velocity vector (nb_vel - ego_vel)
```

Returns `float('inf')` when vehicles are diverging or stationary relative to each other. A finite positive value means they are on a converging path.

### Closest Point of Approach (CPA)

```
compute_cpa(ego_lat, ego_lon, ego_spd, ego_hdg,
            nb_lat,  nb_lon,  nb_spd,  nb_hdg,
            lookahead=5.0, step_s=0.5) → float (metres)
```

Samples projected positions every `step_s` seconds over a `lookahead` window and returns the minimum pairwise distance. This catches near-miss scenarios where TTC would be infinite (e.g. vehicles crossing paths but not quite colliding head-on).

### All-pairs computation

```python
def compute_all_pairs(registry: dict) -> dict:
    """
    Input:  registry = { vehicle_id: {lat, lon, spd, hdg, ...}, ... }
    Output: matrix   = { 'A-B': {dist, ttc, cpa, alert}, 'A-C': {...}, ... }
    """
```

Iterates over all unique pairs `(i, j)` where `i < j` (avoids computing `A-B` and `B-A` separately). Called on every decoded BSM frame — because the gateway receives frames at 2–10 Hz per vehicle, the matrix is always fresh.

### Alert classification

| Level | Condition | Meaning |
|-------|-----------|---------|
| `RED` | TTC < 3 s **and** CPA < 30 m | Imminent collision — vehicles are converging fast and will get very close |
| `AMBER` | TTC < 8 s **and** CPA < 80 m | Potential conflict — driver attention required |
| `GREEN` | Otherwise | Safe separation |

Both conditions must be true simultaneously. A high TTC with a small CPA (vehicles pass close but not imminently) stays AMBER. A very short TTC with a large CPA (vehicles converging fast but will miss by 100 m) stays GREEN.

---

## 6. Project layout

```
roadlink/
│
├── requirements.txt                  ← Python dependencies
│
├── backend/
│   │
│   ├── bsm_codec.py                  ← 28-byte BSM frame encode/decode + CRC-16
│   │
│   ├── obu/
│   │   ├── __init__.py
│   │   ├── node.py                   ← OBUNode: tick loop, tx thread, rx thread
│   │   └── path_engine.py            ← PathProfile per vehicle type, GPS stepping
│   │
│   ├── collision_engine/
│   │   ├── __init__.py
│   │   └── engine.py                 ← haversine, TTC, CPA, alert_level,
│   │                                    compute_all_pairs 
│   │
│   └── gateway/
│       ├── __init__.py
│       ├── gateway.py                ← asyncio entry point: UDP + WS + REST
│       └── registry.py               ← VehicleRegistry: spawn, kill, update, get
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                   ← root component, layout
│       │
│       ├── store/
│       │   └── vehicleStore.js       ← Zustand store: vehicles, matrix, selectedId
│       │
│       ├── hooks/
│       │   └── useWS.js              ← WebSocket connect, parse, dispatch
│       │
│       └── components/
│           ├── MapCanvas.jsx         ← Leaflet map, custom icons, click handler
│           ├── VehicleList.jsx       ← Left sidebar: vehicle rows + Add button
│           ├── DetailPanel.jsx       ← Right sidebar: telemetry + nearby + chart
│           ├── SpawnForm.jsx         ← Type picker + name input + POST /api/vehicles
│           └── AlertBar.jsx          ← Top bar: global worst-case alert pill
│
└── tests/
    └── validate_collision.py         ← 6-scenario offline test suite + plots
```

---

## 7. Tech stack

### Backend

| Component | Library / Tool | Version | Purpose |
|-----------|---------------|---------|---------|
| OBU engine | Python stdlib | 3.11+ | `threading.Thread` per vehicle, `socket` UDP |
| BSM codec | Python `struct` | stdlib | Pack/unpack 28-byte frame, CRC-16 |
| Gateway event loop | `asyncio` | stdlib | Non-blocking UDP rx + WS fan-out |
| WebSocket server | `websockets` | ≥ 11.0 | Dashboard push, auto-reconnect safe |
| REST API | `aiohttp` | ≥ 3.9 | `POST /api/vehicles`, `DELETE /api/vehicles/{id}` |
| Collision math | `math` | stdlib | Haversine, heading vectors, TTC, CPA |
| Test plots | `matplotlib`, `numpy` | ≥ 3.7, ≥ 1.24 | Offline validation suite |

### Frontend

| Component | Library | Version | Purpose |
|-----------|---------|---------|---------|
| UI framework | React | 18.x | Component tree, hooks |
| Build tool | Vite | 5.x | HMR dev server, fast build |
| Map | Leaflet + react-leaflet | 1.9.x / 4.x | OSM tile layer, markers, polylines |
| State | Zustand | 4.x | Minimal global store, no boilerplate |
| Charts | Recharts | 2.x | TTC/distance/CPA line charts |
| HTTP client | `fetch` API | browser | `POST`/`DELETE` to REST gateway |

---

## 8. Prerequisites

### Python

- Python **3.11 or newer** (uses `match` syntax and `asyncio.TaskGroup` internally)
- `pip` package manager

```bash
python --version   # must be ≥ 3.11
```

### Node.js

- Node.js **18 or newer**
- `npm` 8 or newer

```bash
node --version     # must be ≥ 18
npm --version      # must be ≥ 8
```

### Network

- Ports **5005** (UDP), **8765** (WebSocket), **8080** (REST HTTP), **5173** (Vite dev) must be free on localhost
- No external network access required — all traffic is loopback

---

## 9. Installation

### Step 1 — clone or download the project

```bash
git clone https://github.com/your-org/roadlink.git
cd roadlink
```

### Step 2 — Python dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` contents:

```
websockets>=11.0
aiohttp>=3.9
matplotlib>=3.7
numpy>=1.24
```

No virtual environment is strictly required, but recommended:

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows PowerShell
pip install -r requirements.txt
```

### Step 3 — frontend dependencies

```bash
cd frontend
npm install
```

This installs React, Vite, Leaflet, react-leaflet, Zustand, and Recharts as declared in `package.json`.

---

## 10. Running the simulation

The simulation requires two terminals. Three if you want to run the offline validator as well.

### Terminal 1 — start the gateway

The gateway must start first. It owns the UDP socket, WebSocket server, and REST API.

```bash
cd backend/gateway
python gateway.py
```

Expected output:

```
═══════════════════════════════════════════════════════
  ROADLINK — Gateway
  UDP  listener  : 127.0.0.1:5005
  WebSocket      : ws://127.0.0.1:8765
  REST API       : http://127.0.0.1:8080
  Ctrl+C to stop
═══════════════════════════════════════════════════════
[GW] Ready — waiting for OBU connections and dashboard clients...
```

The gateway starts with **zero vehicles**. OBUs are spawned via the dashboard or REST API.

### Terminal 2 — start the React dashboard

```bash
cd frontend
npm run dev
```

Expected output:

```
  VITE v5.x.x  ready in 312 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

Open `http://localhost:5173` in your browser. You will see:

- An empty OpenStreetMap canvas centred on the simulation boundary
- "DISCONNECTED" badge in the top bar (turns LIVE within 1 second of gateway start)
- An empty vehicle list in the left sidebar
- An "Add vehicle" button

### Step 3 — spawn your first vehicles

**Option A — via the dashboard (recommended):**

1. Click **Add vehicle** in the left sidebar
2. Select type: `car`, `truck`, or `bike`
3. Type a name (e.g. `Car A`)
4. Click **Spawn OBU**
5. The vehicle marker appears on the map within one frame interval (~200 ms)
6. Repeat for as many vehicles as you want

**Option B — via curl / REST API:**

```bash
curl -X POST http://localhost:8080/api/vehicles \
  -H "Content-Type: application/json" \
  -d '{"type": "car", "name": "Car A"}'
```

### Optional — run the offline collision validator

```bash
cd tests
python validate_collision.py
```

This runs 6 pre-defined scenarios against the collision engine and saves trajectory plots to `tests/collision_validation.png`. Useful to confirm the math is correct before trusting the live simulation.

---

## 11. Using the dashboard

### Map canvas (centre)

- **Vehicle markers** are coloured circles with a letter label. The colour matches the vehicle's current worst alert state: blue (neutral/GREEN), amber (AMBER), red (RED).
- A **heading arrow** extends from each marker showing the direction of travel.
- A **trail polyline** shows the last 80 positions of each vehicle.
- A **dashed red line** connects any pair of vehicles currently in RED alert, labelled with the live TTC.
- **Click any marker** to select that vehicle. The right sidebar switches to that vehicle's detail panel.
- The map auto-pans to keep all vehicles in view. It will not zoom out past level 16.

### Left sidebar — vehicle list

- Each row shows: colour dot, vehicle name, type badge, worst-case alert badge.
- The currently selected vehicle row is highlighted.
- Click any row to select that vehicle (same as clicking the map marker).
- The **Add vehicle** button opens the spawn form below the list.
- The **spawn form** has a type dropdown (`car` / `truck` / `bike`), a name text input, and a **Spawn OBU** button. After spawning, the form clears automatically.

### Right sidebar — vehicle detail panel

When a vehicle is selected, the right sidebar shows:

**Telemetry section**

| Field | Description |
|-------|-------------|
| Lat / Lon | Current GPS position to 6 decimal places |
| Speed | In metres per second |
| Heading | Compass degrees, 0° = North |
| Brake | `ACTIVE` (red) or `OFF` (green) |
| Tx rate | Current BSM broadcast rate (2 Hz normal, 10 Hz when braking) |

**Nearby vehicles section**

Lists every other vehicle sorted by TTC ascending (most dangerous first). For each neighbour:

- Name + alert badge
- TTC in seconds (or `∞` if diverging)
- CPA in metres
- Current separation distance in metres

**TTC chart**

A live line chart showing TTC over the last 60 seconds for the most critical pair involving the selected vehicle. Reference lines at 3 s (RED threshold) and 8 s (AMBER threshold).

**Alert log**

Scrollable feed of alert state changes and brake events, most recent first. Each entry shows: timestamp, pair, alert level, TTC, distance.

**Delete button**

The trash icon button in the detail panel header sends `DELETE /api/vehicles/{id}` to the gateway. The OBU thread is killed, the vehicle disappears from the registry, and the next WebSocket broadcast omits it. The marker vanishes from the map immediately.

---

## 12. REST API reference

Base URL: `http://127.0.0.1:8080`

### `POST /api/vehicles` — spawn a new vehicle

Starts a new `OBUNode` thread. The vehicle begins broadcasting within one tick interval.

**Request body:**

```json
{
  "type": "car",
  "name": "Car A"
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `type` | string | yes | `"car"`, `"truck"`, `"bike"` |
| `name` | string | yes | Any non-empty string, max 32 chars |

**Response `201 Created`:**

```json
{
  "id": "a3f9c1",
  "name": "Car A",
  "type": "car",
  "vehicle_id": 41977,
  "status": "running"
}
```

| Field | Description |
|-------|-------------|
| `id` | Internal registry key used for deletion |
| `vehicle_id` | Numeric ID embedded in BSM frames (uint32) |
| `status` | Always `"running"` on success |

**Error responses:**

| Code | Body | Cause |
|------|------|-------|
| `400` | `{"error": "invalid type"}` | `type` not in `["car","truck","bike"]` |
| `400` | `{"error": "name required"}` | `name` missing or empty |
| `409` | `{"error": "name already exists"}` | Another vehicle with this name is running |

---

### `GET /api/vehicles` — list all running vehicles

**Response `200 OK`:**

```json
{
  "vehicles": [
    { "id": "a3f9c1", "name": "Car A",   "type": "car",   "vehicle_id": 41977 },
    { "id": "b7d2e4", "name": "Truck B", "type": "truck", "vehicle_id": 47058 },
    { "id": "c1a8f0", "name": "Bike C",  "type": "bike",  "vehicle_id": 49648 }
  ],
  "count": 3
}
```

---

### `DELETE /api/vehicles/{id}` — kill a vehicle

Sends a stop signal to the OBU thread. The thread exits cleanly within one tick cycle (≤ 500 ms). The vehicle is removed from the registry and omitted from the next WebSocket broadcast.

**Path parameter:** `id` — the `id` field returned by `POST /api/vehicles`.

**Response `200 OK`:**

```json
{
  "id": "a3f9c1",
  "name": "Car A",
  "status": "stopped"
}
```

**Error responses:**

| Code | Body | Cause |
|------|------|-------|
| `404` | `{"error": "not found"}` | No vehicle with this ID |

---

### `GET /api/health` — gateway health check

**Response `200 OK`:**

```json
{
  "status": "ok",
  "vehicles": 3,
  "ws_clients": 1,
  "uptime_s": 142.7
}
```

---

## 13. WebSocket payload reference

The gateway broadcasts one JSON frame per incoming BSM packet. At 3 active vehicles transmitting at 5 Hz each, that is ~15 frames per second.

**Connection URL:** `ws://127.0.0.1:8765`

**Handshake:** after connecting, the dashboard must send:

```json
{ "type": "dashboard" }
```

The gateway will then begin forwarding frames. Any client that does not send the handshake within 5 seconds is disconnected.

**Frame structure:**

```json
{
  "t": 42.14,
  "vehicles": {
    "a3f9c1": {
      "id":         "a3f9c1",
      "name":       "Car A",
      "type":       "car",
      "lat":        12.972841,
      "lon":        77.594612,
      "spd":        18.4,
      "hdg":        47.2,
      "accel":      -1.2,
      "brake":      1,
      "tx_rate":    10,
      "timestamp_ms": 42100
    },
    "b7d2e4": { ... },
    "c1a8f0": { ... }
  },
  "collision_matrix": {
    "a3f9c1-b7d2e4": {
      "dist":   210.3,
      "ttc":    9999,
      "cpa":    195.0,
      "alert":  "GREEN"
    },
    "a3f9c1-c1a8f0": {
      "dist":   38.1,
      "ttc":    1.8,
      "cpa":    14.0,
      "alert":  "RED"
    },
    "b7d2e4-c1a8f0": {
      "dist":   188.2,
      "ttc":    9999,
      "cpa":    175.0,
      "alert":  "GREEN"
    }
  }
}
```

**Field reference:**

| Path | Type | Description |
|------|------|-------------|
| `t` | float | Seconds since gateway start |
| `vehicles.{id}.lat` | float | Latitude, degrees WGS-84 |
| `vehicles.{id}.lon` | float | Longitude, degrees WGS-84 |
| `vehicles.{id}.spd` | float | Speed, metres per second |
| `vehicles.{id}.hdg` | float | Heading, degrees (0 = North, clockwise) |
| `vehicles.{id}.accel` | float | Longitudinal acceleration, m/s² |
| `vehicles.{id}.brake` | int | `0` = off, `1` = braking |
| `vehicles.{id}.tx_rate` | int | Current BSM broadcast rate in Hz |
| `collision_matrix.{pair}.dist` | float | Haversine distance between the pair, metres |
| `collision_matrix.{pair}.ttc` | float | Time To Collision, seconds. `9999` = diverging / ∞ |
| `collision_matrix.{pair}.cpa` | float | Closest Point of Approach, metres |
| `collision_matrix.{pair}.alert` | string | `"GREEN"`, `"AMBER"`, or `"RED"` |

**Pair key format:** `"{lower_id}-{higher_id}"` — always the lexicographically smaller ID first, so each pair has exactly one key regardless of which vehicle sent the triggering frame.

---

## 14. Vehicle types and path profiles

Each vehicle type has a `PathProfile` that controls its simulated movement behaviour. All profiles share the same GPS path engine (random walk with boundary clamping and smooth heading/speed steering), but differ in speed range, turn aggressiveness, and brake probability.

### Car

```python
PathProfile(
    speed_min         = 8.0,    # m/s  (~29 km/h) — minimum cruise speed
    speed_max         = 25.0,   # m/s  (~90 km/h) — maximum speed
    initial_speed     = 18.0,   # m/s  (~65 km/h) — starting speed
    turn_rate_max     = 45.0,   # °/s  — maximum heading change per second
    turn_interval     = (3, 8), # seconds between heading decisions
    brake_probability = 0.08,   # per-tick probability of a brake event
    vehicle_class     = 0,      # BSM vehicle_cls field
)
```

### Truck

```python
PathProfile(
    speed_min         = 6.0,
    speed_max         = 22.0,
    initial_speed     = 15.0,
    turn_rate_max     = 30.0,   # trucks turn more slowly
    turn_interval     = (5, 12),
    brake_probability = 0.05,
    vehicle_class     = 1,
)
```

### Bike

```python
PathProfile(
    speed_min         = 4.0,
    speed_max         = 15.0,
    initial_speed     = 10.0,
    turn_rate_max     = 60.0,   # bikes manoeuvre quickly
    turn_interval     = (2, 6),
    brake_probability = 0.12,   # bikes brake more often
    vehicle_class     = 2,
)
```

### Simulation boundary

All vehicle types are constrained to the same geo-fence (a ~500 m × 500 m box around the NH48 corridor in Chennai). When a vehicle approaches the boundary, its path engine steers it back toward the centre with a random offset of ±30°.

```python
BOUNDARY = {
    "lat_min": 12.9700,
    "lat_max": 12.9750,
    "lon_min": 77.5930,
    "lon_max": 77.5970,
}
```

---

## 15. Alert thresholds

| Level | TTC condition | CPA condition | Dashboard effect |
|-------|--------------|--------------|-----------------|
| `GREEN` | ≥ 8 s **or** diverging | ≥ 80 m | Blue/teal marker, no highlight |
| `AMBER` | < 8 s | < 80 m | Amber marker, AMBER pill in header if worst pair |
| `RED` | < 3 s | < 30 m | Red pulsing marker, RED pill in header, red dashed connector line on map |

**Both conditions must be simultaneously true** for a level to apply. The system checks TTC < threshold **and** CPA < threshold. This prevents false alerts when two vehicles are converging but will clearly miss each other by a large margin.

**Tx rate escalation:** when a vehicle's `brake` flag is set, its OBU automatically increases its broadcast rate from 2 Hz to 10 Hz. When a vehicle receives a frame with `brake=1` from a neighbour, the gateway notes this and uses it as a soft signal to poll the collision engine immediately.

---

## 16. Configuration reference

All configuration lives in a single `config.py` at the project root (or as constants in each module for the MVP). The values below are the defaults:

### Gateway (`backend/gateway/gateway.py`)

```python
UDP_HOST       = "127.0.0.1"
UDP_PORT       = 5005           # shared BSM broadcast bus
WS_HOST        = "127.0.0.1"
WS_PORT        = 8765           # WebSocket push to dashboard
REST_HOST      = "127.0.0.1"
REST_PORT      = 8080           # aiohttp REST API
WS_HANDSHAKE_TIMEOUT = 5.0     # seconds to wait for {"type":"dashboard"}
MAX_VEHICLES   = 20            # safety limit on concurrent OBU threads
```

### OBU node (`backend/obu/node.py`)

```python
BSM_BROADCAST_ADDR = ("127.0.0.1", 5005)
TICK_RATE_NORMAL   = 2          # Hz — base broadcast frequency
TICK_RATE_BRAKE    = 10         # Hz — elevated during brake event
RX_BUFFER_SIZE     = 64         # bytes — BSM frame is 28 bytes, headroom for safety
TRAIL_HISTORY      = 80         # positions to keep for map trail
```

### Collision engine (`backend/collision_engine/engine.py`)

```python
TTC_RED    = 3.0    # seconds
TTC_AMBER  = 8.0    # seconds
CPA_RED    = 30.0   # metres
CPA_AMBER  = 80.0   # metres
CPA_LOOKAHEAD = 5.0 # seconds of trajectory to sample
CPA_STEP_S    = 0.5 # sampling interval within lookahead window
```

### Frontend (`frontend/src/store/vehicleStore.js`)

```javascript
const WS_URL          = "ws://127.0.0.1:8765";
const REST_BASE       = "http://127.0.0.1:8080";
const RECONNECT_MS    = 2000;    // WebSocket reconnect delay
const TRAIL_MAX       = 80;      // positions kept per vehicle for map trail
const CHART_WINDOW    = 60;      // seconds of TTC history shown in chart
```

---

## 17. Adding a vehicle programmatically

### Via Python (direct registry access — for testing)

```python
import sys
sys.path.insert(0, 'backend')

from gateway.registry import VehicleRegistry
from obu.node import OBUNode

registry = VehicleRegistry()
node = OBUNode(name="Car E", vehicle_type="car", registry=registry)
node.start()   # spawns tx + rx threads

# ... later ...
node.stop()    # graceful shutdown
```

### Via REST API (from any language)

```bash
# JavaScript / fetch
const resp = await fetch('http://127.0.0.1:8080/api/vehicles', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ type: 'bike', name: 'Bike E' })
});
const { id } = await resp.json();

# Later — delete it
await fetch(`http://127.0.0.1:8080/api/vehicles/${id}`, { method: 'DELETE' });
```

```python
# Python / requests
import requests

r = requests.post('http://127.0.0.1:8080/api/vehicles',
                  json={'type': 'car', 'name': 'Car F'})
vehicle_id = r.json()['id']

# Later
requests.delete(f'http://127.0.0.1:8080/api/vehicles/{vehicle_id}')
```

---

## 18. Extending — adding a new vehicle type

### Step 1 — add a path profile in `backend/obu/path_engine.py`

```python
PROFILES = {
    "car":       PathProfile(speed_min=8,  speed_max=25, ...),
    "truck":     PathProfile(speed_min=6,  speed_max=22, ...),
    "bike":      PathProfile(speed_min=4,  speed_max=15, ...),
    # Add your new type here:
    "emergency": PathProfile(
        speed_min=15, speed_max=40,
        turn_rate_max=60,
        turn_interval=(2, 5),
        brake_probability=0.03,
        vehicle_class=3,           # 3 = emergency in BSM spec
    ),
}
```

### Step 2 — allow the new type in the gateway REST handler (`backend/gateway/gateway.py`)

```python
VALID_TYPES = {"car", "truck", "bike", "emergency"}   # add here
```

### Step 3 — add a marker icon in the frontend (`frontend/src/components/MapCanvas.jsx`)

```javascript
const VEHICLE_ICONS = {
  car:       makeIcon("#378ADD", "C"),
  truck:     makeIcon("#1D9E75", "T"),
  bike:      makeIcon("#D85A30", "B"),
  emergency: makeIcon("#E24B4A", "E"),   // add here
};
```

### Step 4 — add the type to the spawn form dropdown (`frontend/src/components/SpawnForm.jsx`)

```jsx
<select name="type">
  <option value="car">car</option>
  <option value="truck">truck</option>
  <option value="bike">bike</option>
  <option value="emergency">emergency</option>
</select>
```

That is all that is required. The OBU thread, BSM frame, collision engine, and WebSocket payload all handle arbitrary vehicle types without further changes.

---

## 19. Troubleshooting

### Gateway does not start — "address already in use"

Another process is using port 5005, 8765, or 8080.

```bash
# Find and kill the process on port 5005 (macOS / Linux)
lsof -ti:5005 | xargs kill -9
lsof -ti:8765 | xargs kill -9
lsof -ti:8080 | xargs kill -9

# Windows
netstat -ano | findstr :5005
taskkill /PID <pid> /F
```

### Dashboard shows "DISCONNECTED"

- Confirm the gateway is running and printed "Ready" before opening the browser
- Check the browser console for WebSocket errors
- Make sure no browser extension or firewall is blocking `ws://127.0.0.1:8765`
- Try a hard refresh (`Ctrl+Shift+R` / `Cmd+Shift+R`)

### Vehicles spawn but do not move on the map

- Open browser DevTools → Network → WS → inspect incoming frames
- If frames arrive but the map does not update, check for JavaScript errors in the console
- Confirm `react-leaflet` and `leaflet` are installed: `cd frontend && npm list leaflet`

### All alerts stay GREEN for a long time

This is expected. Vehicles start at random positions within the 500 m boundary and may take 10–30 seconds to converge into close proximity. Spawn 4+ vehicles to increase the chance of near-misses. You can also temporarily tighten `BOUNDARY` in `path_engine.py` to force vehicles into a smaller area.

### `ModuleNotFoundError: No module named 'websockets'`

```bash
pip install websockets aiohttp
```

If using a virtual environment, confirm it is activated before running the gateway.

### `ModuleNotFoundError: No module named 'aiohttp'`

```bash
pip install aiohttp
```

### OBU thread does not stop cleanly after DELETE

The thread is guarded by a `threading.Event`. If it does not exit within 2 seconds, the gateway logs a warning and forcibly removes the vehicle from the registry. The thread becomes a daemon thread and will be collected when the gateway process exits.

### Vite port 5173 already in use

```bash
cd frontend
npm run dev -- --port 5174
```

Update `VITE_WS_URL` if you have moved the gateway ports too.

### CRC failures in the console (`Bad frame — CRC fail or wrong size`)

This should not happen in normal operation because all traffic is loopback. If you see CRC failures:

- Confirm all OBU nodes and the gateway are running the same version of `bsm_codec.py`
- Check that `FRAME_SIZE = 28` matches in both encoder and decoder
- Do not modify the struct format string `_STRUCT` without updating both sides simultaneously

---

## 20. Known limitations (MVP)

- **Loopback only.** All communication is `127.0.0.1`. Real multi-machine V2V would require network interfaces, DSRC/C-V2X radio, or at minimum a proper UDP multicast group across machines.
- **No persistence.** Vehicle state is in-memory. Restarting the gateway clears all vehicles and history.
- **No authentication.** The REST API and WebSocket are unauthenticated. This is fine for local simulation; do not expose ports publicly.
- **UDP packet ordering not guaranteed.** In practice on loopback this is never an issue, but the collision engine does not account for out-of-order frames.
- **Collision engine is 2D planar.** Altitude is not modelled. CPA does not account for vertical separation (relevant for multi-level roads or parking structures).
- **No real map matching.** Vehicles drive through buildings and water. The GPS path engine is a constrained random walk, not a road-network-aware router.
- **Max ~20 vehicles recommended.** At 20 vehicles × 5 Hz each = 100 BSM frames/second, and 190 unique pairs per frame, the gateway runs the collision engine at ~19,000 pair-evaluations per second. On a modern laptop this is comfortably under 1% CPU. Beyond 30 vehicles the O(N²) cost begins to be noticeable.

---

## 21. Roadmap

Features planned beyond MVP, in rough priority order:

- **Multi-machine support** — UDP multicast group so real laptops/phones can join the mesh as OBUs
- **Road-network path engine** — OSRM or Valhalla integration so vehicles follow actual roads
- **Real ESP32 firmware bridge** — a UDP-to-serial adapter so a physical ESP32 running real BSM firmware can join the simulation mesh
- **Replay mode** — record all BSM frames to a file, replay at any speed for post-incident analysis
- **RSU (Road-Side Unit)** — a static node that aggregates alerts from all passing vehicles and posts to a central server
- **Pedestrian type** — a slow-moving node that represents a person crossing the road, with a much smaller collision radius
- **Weather / visibility model** — reduce CPA lookahead and increase alert thresholds when simulated visibility is low
- **Mobile dashboard** — responsive React layout so the dashboard is usable on a phone screen
- **Persistence** — SQLite log of all BSM frames and alert events, queryable via a `/api/history` endpoint

---

## License

MIT — see `LICENSE` file.

---

## Acknowledgements

- BSM frame format inspired by SAE J2735 Basic Safety Message specification
- Collision math (TTC closing-velocity method, CPA sampling) adapted from published V2V safety literature
- Map tiles © OpenStreetMap contributors (ODbL licence)
- Built on top of the ROADLINK V1 two-vehicle proof-of-concept