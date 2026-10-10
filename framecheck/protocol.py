"""The demonstration protocol only; real protocols supply their own test suite."""

HEADER = b"\xaa\x55"
MAX_PAYLOAD = 64
DESCRIPTION = {
    "name": "framecheck-demo-v1",
    "layout": "AA 55 | len:u8 | seq:u8 | type:u8 | payload:len | crc16:le",
    "max_payload": MAX_PAYLOAD,
    "crc": "CRC-16/CCITT-FALSE, poly=0x1021, init=0xffff, refin=false, refout=false, xorout=0; covers len..payload",
    "recovery": "invalid length or CRC: discard one byte and search again; incomplete candidates: retain until next feed",
}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def message(seq: int, kind: int, payload: bytes) -> dict:
    return {"seq": seq, "type": kind, "payload_hex": payload.hex()}


def encode(seq: int, kind: int, payload: bytes) -> bytes:
    if not 0 <= seq <= 255 or not 0 <= kind <= 255:
        raise ValueError("seq and type must fit u8")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("demo protocol payload must be <= 64 bytes")
    body = bytes([len(payload), seq, kind]) + payload
    return HEADER + body + crc16(body).to_bytes(2, "little")


class DemoParser:
    """Streaming implementation, with deliberate faults for verifying the harness."""

    def __init__(self, bug: int = 0):
        if bug not in range(5):
            raise ValueError("bug must be 0..4")
        self.bug = bug
        self.reset()

    def reset(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        if self.bug == 1:
            self.buffer.clear()
        self.buffer.extend(data)
        out = []
        while self.buffer:
            index = self.buffer.find(HEADER)
            if index < 0:
                self.buffer[:] = b"\xaa" if self.buffer[-1:] == b"\xaa" else b""
                break
            if index:
                if self.bug == 4:
                    self.buffer.clear()
                    break
                del self.buffer[:index]
            if len(self.buffer) < 3:
                break
            size = self.buffer[2]
            if size > MAX_PAYLOAD:
                del self.buffer[0]
                continue
            total = size + 7
            if len(self.buffer) < total:
                break
            raw = bytes(self.buffer[:total])
            if self.bug != 3 and crc16(raw[2:-2]) != int.from_bytes(raw[-2:], "little"):
                del self.buffer[0]
                continue
            out.append(message(raw[3], raw[4], raw[5:-2]))
            del self.buffer[:total]
            if self.bug == 2:
                self.buffer.clear()
                break
        return out
