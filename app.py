import json
import math
import queue
import random
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Deque, Dict

from flask import Flask, Response, render_template

UDP_BIND = "0.0.0.0"
UDP_PULSE_PORT = 50050
UDP_EMITTER_PORT = 50051
HTTP_PORT = 8080
MAX_PULSES = 240
CLIENT_QUEUE_SIZE = 512

SIM_EMITTERS = [
    {"id": "alpha", "base": 28, "swing": 16, "freq": 9340.0, "level": -48.0},
    {"id": "bravo", "base": 146, "swing": 28, "freq": 9780.0, "level": -52.0},
    {"id": "charlie", "base": 292, "swing": 22, "freq": 10420.0, "level": -57.0},
    {"id": "delta", "base": 100, "swing": 100, "freq": 14420.0, "level": -37.0},
    {"id": "echo", "base": 200, "swing": 1, "freq": 13420.0, "level": -77.0},
]


@dataclass
class Pulse:
    timestamp: float
    angle_deg: float
    strength: float
    width_ms: float
    frequency_mhz: float
    emitter_id: str


@dataclass
class EmitterStatus:
    timestamp: float
    emitter_id: str
    frequency_mhz: float
    level: float


pulse_buffer: Deque[Pulse] = deque(maxlen=MAX_PULSES)
emitter_table: dict[str, EmitterStatus] = {}
clients: set[queue.Queue] = set()
state_lock = threading.Lock()


def pulse_to_dict(pulse: Pulse) -> Dict:
    data = asdict(pulse)
    data["age_ms"] = max(0.0, (time.time() - pulse.timestamp) * 1000.0)
    return data


def emitter_to_dict(status: EmitterStatus) -> Dict:
    data = asdict(status)
    data["age_ms"] = max(0.0, (time.time() - status.timestamp) * 1000.0)
    return data


def publish_event(event_type: str, payload: Dict) -> None:
    with state_lock:
        active_clients = list(clients)
    stale_clients = []
    event = {"type": event_type, "payload": payload}
    for client_queue in active_clients:
        try:
            client_queue.put_nowait(event)
        except queue.Full:
            try:
                client_queue.get_nowait()
                client_queue.put_nowait(event)
            except Exception:
                stale_clients.append(client_queue)
        except Exception:
            stale_clients.append(client_queue)
    if stale_clients:
        with state_lock:
            for client_queue in stale_clients:
                clients.discard(client_queue)


def pulse_listener() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((UDP_BIND, UDP_PULSE_PORT))
    while True:
        raw, _addr = sock.recvfrom(65535)
        try:
            msg = json.loads(raw.decode("utf-8"))
            pulse = Pulse(
                timestamp=float(msg.get("timestamp", time.time())),
                angle_deg=float(msg["angle_deg"]) % 360.0,
                strength=max(0.0, min(1.0, float(msg["strength"]))),
                width_ms=float(msg.get("width_ms", 1.0)),
                frequency_mhz=float(msg.get("frequency_mhz", 1000.0)),
                emitter_id=str(msg.get("emitter_id", "sim")),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        with state_lock:
            pulse_buffer.append(pulse)
            pulse_data = pulse_to_dict(pulse)
        publish_event("pulse", pulse_data)


def emitter_listener() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((UDP_BIND, UDP_EMITTER_PORT))
    while True:
        raw, _addr = sock.recvfrom(65535)
        try:
            msg = json.loads(raw.decode("utf-8"))
            status = EmitterStatus(
                timestamp=float(msg.get("timestamp", time.time())),
                emitter_id=str(msg["emitter_id"]),
                frequency_mhz=float(msg["frequency_mhz"]),
                level=float(msg["level"]),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        with state_lock:
            emitter_table[status.emitter_id] = status
            status_data = emitter_to_dict(status)
        publish_event("emitter_status", status_data)


class UdpSimulator(threading.Thread):
    def __init__(self, pulse_port: int = UDP_PULSE_PORT, emitter_port: int = UDP_EMITTER_PORT, interval: float = 0.04):
        super().__init__(daemon=True)
        self.pulse_port = pulse_port
        self.emitter_port = emitter_port
        self.interval = interval
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.t0 = time.time()

    def run(self) -> None:
        while True:
            now = time.time() - self.t0
            for idx, emitter in enumerate(SIM_EMITTERS):
                phase = now * (0.33 + idx * 0.07)
                angle = emitter["base"] + math.sin(phase) * emitter["swing"] + random.gauss(0, 1.8)
                strength = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(phase * 2.2 + idx)) + random.uniform(-0.08, 0.08)
                frequency = emitter["freq"] + random.uniform(-8.0, 8.0)
                level = emitter["level"] + math.sin(phase * 1.5 + idx) * 6.0 + random.uniform(-1.5, 1.5)

                pulse = {
                    "timestamp": time.time(),
                    "angle_deg": angle % 360.0,
                    "strength": max(0.03, min(1.0, strength)),
                    "width_ms": round(random.uniform(0.12, 2.4), 3),
                    "frequency_mhz": frequency,
                    "emitter_id": emitter["id"],
                }
                emitter_status = {
                    "timestamp": time.time(),
                    "emitter_id": emitter["id"],
                    "frequency_mhz": frequency,
                    "level": level,
                }

                self.sock.sendto(json.dumps(pulse).encode("utf-8"), ("255.255.255.255", self.pulse_port))
                self.sock.sendto(json.dumps(emitter_status).encode("utf-8"), ("255.255.255.255", self.emitter_port))
            time.sleep(self.interval)


app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "radar-pulse-view.html",
        pulse_port=UDP_PULSE_PORT,
        emitter_port=UDP_EMITTER_PORT,
    )


@app.route("/api/snapshot")
def snapshot():
    with state_lock:
        pulses = [pulse_to_dict(p) for p in list(pulse_buffer)]
        emitters = [emitter_to_dict(v) for v in sorted(emitter_table.values(), key=lambda x: x.emitter_id)]
    return {
        "pulses": pulses,
        "emitters": emitters,
        "pulse_port": UDP_PULSE_PORT,
        "emitter_port": UDP_EMITTER_PORT,
    }


@app.route("/stream")
def stream():
    client_queue: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)
    with state_lock:
        clients.add(client_queue)
        history = {
            "pulses": [pulse_to_dict(p) for p in list(pulse_buffer)],
            "emitters": [emitter_to_dict(v) for v in sorted(emitter_table.values(), key=lambda x: x.emitter_id)],
        }

    def event_stream():
        try:
            yield "retry: 1000\n"
            yield f"event: bootstrap\ndata: {json.dumps(history)}\n\n"
            while True:
                try:
                    event = client_queue.get(timeout=10)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['payload'])}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with state_lock:
                clients.discard(client_queue)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response


if __name__ == "__main__":
    threading.Thread(target=pulse_listener, daemon=True).start()
    threading.Thread(target=emitter_listener, daemon=True).start()
    UdpSimulator().start()
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, threaded=True)
