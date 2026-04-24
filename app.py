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

UDP_PORT = 50050
UDP_BIND = "0.0.0.0"
HTTP_PORT = 8080
MAX_PULSES = 180
CLIENT_QUEUE_SIZE = 256


@dataclass
class Pulse:
    timestamp: float
    angle_deg: float
    strength: float
    width_ms: float
    frequency_mhz: float
    emitter_id: str


pulse_buffer: Deque[Pulse] = deque(maxlen=MAX_PULSES)
clients: set[queue.Queue] = set()
state_lock = threading.Lock()


def pulse_to_dict(pulse: Pulse) -> Dict:
    data = asdict(pulse)
    data["age_ms"] = max(0.0, (time.time() - pulse.timestamp) * 1000.0)
    return data


def udp_listener() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((UDP_BIND, UDP_PORT))

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
            active_clients = list(clients)

        stale_clients = []
        for client_queue in active_clients:
            try:
                client_queue.put_nowait(pulse_data)
            except queue.Full:
                try:
                    client_queue.get_nowait()
                    client_queue.put_nowait(pulse_data)
                except Exception:
                    stale_clients.append(client_queue)
            except Exception:
                stale_clients.append(client_queue)

        if stale_clients:
            with state_lock:
                for client_queue in stale_clients:
                    clients.discard(client_queue)


class UdpPulseSimulator(threading.Thread):
    def __init__(self, port: int = UDP_PORT, interval: float = 0.004):
        super().__init__(daemon=True)
        self.port = port
        self.interval = interval
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.t0 = time.time()
        self.emitters = [
            {"id": "alpha", "base": 28, "swing": 16, "freq": 9340},
            {"id": "bravo", "base": 146, "swing": 28, "freq": 9780},
            {"id": "charlie", "base": 292, "swing": 22, "freq": 10420},
            {"id": "delta", "base": 211, "swing": 99, "freq": 11420},
            {"id": "echo", "base": 100, "swing": 2, "freq": 12420},
        ]

    def run(self) -> None:
        while True:
            now = time.time() - self.t0
            for idx, emitter in enumerate(self.emitters):
                phase = now * (0.33 + idx * 0.07)
                angle = emitter["base"] + math.sin(phase) * emitter["swing"] + random.gauss(0, 1.8)
                strength = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(phase * 2.2 + idx)) + random.uniform(-0.08, 0.08)
                pulse = {
                    "timestamp": time.time(),
                    "angle_deg": angle % 360.0,
                    "strength": max(0.03, min(1.0, strength)),
                    "width_ms": round(random.uniform(0.12, 2.4), 3),
                    "frequency_mhz": emitter["freq"] + random.uniform(-8.0, 8.0),
                    "emitter_id": emitter["id"],
                }
                self.sock.sendto(json.dumps(pulse).encode("utf-8"), ("255.255.255.255", self.port))
            time.sleep(self.interval)


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("radar-pulse-view.html", udp_port=UDP_PORT)


@app.route("/api/snapshot")
def snapshot():
    with state_lock:
        data = [pulse_to_dict(pulse) for pulse in list(pulse_buffer)]
    return {"pulses": data, "count": len(data), "udp_port": UDP_PORT}


@app.route("/stream")
def stream():
    client_queue: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE_SIZE)
    with state_lock:
        clients.add(client_queue)
        history = [pulse_to_dict(pulse) for pulse in list(pulse_buffer)]

    def event_stream():
        try:
            yield "retry: 1000\n"
            yield f"event: bootstrap\ndata: {json.dumps({'pulses': history})}\n\n"
            while True:
                try:
                    item = client_queue.get(timeout=10)
                    yield f"event: pulse\ndata: {json.dumps(item)}\n\n"
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
    threading.Thread(target=udp_listener, daemon=True).start()
    UdpPulseSimulator().start()
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False, threaded=True)
