"""
BSM-lite Codec — 28-byte fixed-length frame encoder/decoder with CRC-16.

Frame layout (28 bytes total):
    Offset  Bytes  Type    Field
    ------  -----  ------  ---------------
    0       2      u8[2]   preamble         0xAA 0xBB
    2       1      u8      version          0x01
    3       4      u32     vehicle_id       big-endian
    7       4      i32     lat_fp           lat × 1e7
    11      4      i32     lon_fp           lon × 1e7
    15      2      u16     spd_cms          speed in cm/s
    17      2      u16     hdg_ddeg         heading in deci-degrees
    19      1      i8      accel_b          accel × 10, clamped ±127
    20      1      u8      brake            0 or 1
    21      1      u8      vehicle_cls      0=car 1=truck 2=bike 3=emergency
    22      4      u32     timestamp_ms     ms since node start
    26      2      u16     crc16            CRC-16/CCITT-FALSE over [0:26]

CRC-16 algorithm: CCITT-FALSE
    Polynomial: 0x1021
    Init:       0xFFFF
    No input/output reflection
"""

import struct
from typing import Optional


# ── Frame constants ──────────────────────────────────────────────────────────

PREAMBLE       = bytes([0xAA, 0xBB])
VERSION        = 0x01
FRAME_SIZE     = 28

# struct format:  preamble(2B) version(1B) vehicle_id(4B) lat_fp(4B) lon_fp(4B)
#                 spd_cms(2B) hdg_ddeg(2B) accel_b(1B) brake(1B) vehicle_cls(1B)
#                 timestamp_ms(4B) crc16(2B)
_STRUCT_PAYLOAD = ">2s B I i i H H b B B I"      # 26 bytes (everything except CRC)
_STRUCT_FULL    = ">2s B I i i H H b B B I H"     # 28 bytes (with CRC)

_PAYLOAD_SIZE   = struct.calcsize(_STRUCT_PAYLOAD)  # should be 26
_FULL_SIZE      = struct.calcsize(_STRUCT_FULL)      # should be 28

assert _PAYLOAD_SIZE == 26, f"Payload struct size mismatch: {_PAYLOAD_SIZE}"
assert _FULL_SIZE == 28, f"Full struct size mismatch: {_FULL_SIZE}"


# ── CRC-16/CCITT-FALSE ──────────────────────────────────────────────────────

def _crc16_ccitt_false(data: bytes) -> int:
    """
    Compute CRC-16/CCITT-FALSE over the given byte sequence.

    Polynomial: 0x1021
    Initial value: 0xFFFF
    No input/output bit reflection.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


# ── Encoder ──────────────────────────────────────────────────────────────────

def encode(
    vehicle_id:    int,
    lat:           float,
    lon:           float,
    speed_mps:     float,
    heading_deg:   float,
    accel_ms2:     float,
    brake:         int,
    vehicle_class: int,
    timestamp_ms:  int,
) -> bytes:
    """
    Encode vehicle state into a 28-byte BSM-lite frame.

    Args:
        vehicle_id:    Unique node identifier (uint32).
        lat:           Latitude in degrees (WGS-84).
        lon:           Longitude in degrees (WGS-84).
        speed_mps:     Speed in metres per second.
        heading_deg:   Heading in degrees (0 = North, clockwise).
        accel_ms2:     Longitudinal acceleration in m/s².
        brake:         0 = not braking, 1 = braking.
        vehicle_class: 0=car, 1=truck, 2=bike, 3=emergency.
        timestamp_ms:  Milliseconds since node start.

    Returns:
        28-byte BSM frame with CRC-16 appended.
    """
    # Convert floating-point to fixed-point wire format
    lat_fp   = int(round(lat * 1e7))
    lon_fp   = int(round(lon * 1e7))
    spd_cms  = int(round(speed_mps * 100))
    hdg_ddeg = int(round(heading_deg * 10))

    # Clamp acceleration to ±12.7 m/s² (i8 range: ±127 when ×10)
    accel_clamped = max(-12.7, min(12.7, accel_ms2))
    accel_b       = int(round(accel_clamped * 10))

    # Pack the 26-byte payload (without CRC)
    payload = struct.pack(
        _STRUCT_PAYLOAD,
        PREAMBLE,
        VERSION,
        vehicle_id & 0xFFFFFFFF,
        lat_fp,
        lon_fp,
        spd_cms  & 0xFFFF,
        hdg_ddeg & 0xFFFF,
        accel_b,
        brake & 0xFF,
        vehicle_class & 0xFF,
        timestamp_ms & 0xFFFFFFFF,
    )

    # Compute CRC-16 over the payload
    crc = _crc16_ccitt_false(payload)

    # Append CRC to form the complete 28-byte frame
    frame = payload + struct.pack(">H", crc)
    assert len(frame) == FRAME_SIZE, f"Frame size mismatch: {len(frame)}"
    return frame


# ── Decoder ──────────────────────────────────────────────────────────────────

def decode(data: bytes) -> Optional[dict]:
    """
    Decode a 28-byte BSM-lite frame.

    Returns:
        Decoded field dict on success, or None if frame is invalid
        (wrong size, bad preamble, CRC mismatch).
    """
    # Validate frame size
    if len(data) != FRAME_SIZE:
        return None

    # Validate preamble
    if data[0:2] != PREAMBLE:
        return None

    # Extract and verify CRC
    payload  = data[:26]
    crc_recv = struct.unpack(">H", data[26:28])[0]
    crc_calc = _crc16_ccitt_false(payload)

    if crc_recv != crc_calc:
        return None

    # Unpack all fields
    (
        _preamble,
        version,
        vehicle_id,
        lat_fp,
        lon_fp,
        spd_cms,
        hdg_ddeg,
        accel_b,
        brake,
        vehicle_cls,
        timestamp_ms,
    ) = struct.unpack(_STRUCT_PAYLOAD, payload)

    # Convert fixed-point back to floating-point
    return {
        "vehicle_id":    vehicle_id,
        "lat":           lat_fp / 1e7,
        "lon":           lon_fp / 1e7,
        "spd":           spd_cms / 100.0,
        "hdg":           hdg_ddeg / 10.0,
        "accel":         accel_b / 10.0,
        "brake":         brake,
        "vehicle_cls":   vehicle_cls,
        "timestamp_ms":  timestamp_ms,
    }
