# AoA Radar Pulse Viewer

Eine Web‑Anwendung in Python/Frontend‑Canvas, die Radar‑Pulse nach **Angle of Arrival** (AoA) und Signalstärke visualisiert. Pulse erscheinen als farbige Lichtpunkte auf einem Kreis, wobei der Winkel den Einfalls­winkel und der Radius die relative Pegelstärke repräsentiert.

Zusätzlich gibt es einen zweiten UDP‑Datenstrom mit Emitter‑ID, Frequenz und Pegel, der in einer Live‑Tabelle angezeigt wird. Auf der Website kann ein Klick auf einen Tabellen-Eintrag die Pulse im Radar so filtern, dass nur noch dieser Emitter sichtbar bleibt.

## Features

- Serverseitiges Python‑Backend mit:
  - UDP‑Broadcast‑Empfang für Pulse (AoA, Pegel, ID, Frequenz)
  - UDP‑Broadcast‑Empfang für Emitter‑Metadaten (ID, Frequenz, Pegel)
  - Flask‑Webserver mit Server‑Side Events (SSE) für Live‑Stream
- Web‑Frontend (Canvas + HTML/CSS/JS):
  - Kreisförmige Radar‑Ansicht
  - Farben pro Emitter, eindeutig aus der Emitter‑ID gehasht
  - Live‑Tabelle für Emitter‑Daten
  - Klick‑Filter: Klick auf Tabellenzeile ⇒ nur Pulse dieses Emitters sichtbar
  - Optional: Hintergrund‑Pulse (andere Emitter) schwach im Hintergrund
- Inline‑Simulator:
  - Simuliert mehrere Pulse‑Emitter mit pendelndem AoA und variierender Signalstärke
  - Sendet beide Datenströme per UDP‑Broadcast auf separate Ports

## Installation & Start

```bash
git clone https://github.com/dein-benutzer/aor-pulse-viewer.git
cd aor-pulse-viewer

# virtuelle Umgebung (empfohlen)
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# oder auf Windows: .venv\Scripts\activate

# Abhängigkeiten
pip install -r requirements.txt

# Server starten
python app.py
```

Nach erfolgreichem Start läuft der Server unter `http://localhost:8080`. Die UDP‑Ports sind:

- Pulse‑Daten: `50050` (AoA, Pegel, Frequenz, Emitter‑ID)
- Emitter‑Metadaten: `50051` (Emitter‑ID, Frequenz, Pegel)

Der eingebaute Simulator sendet auf beide Ports via UDP‑Broadcast; externe Sender können diese im gleichen JSON‑Format verwenden.

## Datenformat (UDP‑JSON)

**Pulse‑Daten (`/source/pulse_stream`):**
```json
{
  "timestamp": 1710000000.123,
  "angle_deg": 133.7,
  "strength": 0.82,
  "width_ms": 0.44,
  "frequency_mhz": 9784.3,
  "emitter_id": "bravo"
}
```

**Emitter‑Daten (`/source/emitter_stream`):**
```json
{
  "timestamp": 1710000000.123,
  "emitter_id": "bravo",
  "frequency_mhz": 9784.3,
  "level": -51.2
}
```

## Farb‑Logik für Emitter

Die Farben pro Emitter werden nicht hart kodiert, sondern aus der `emitter_id` gehasht und gecacht:

- String‑Hash → deterministischer HSL‑Farbton
- Farbe wird pro `emitter_id` nur einmal berechnet und gespeichert
- Canvas‑Rendering nutzt `rgba(...)`‑Strings aus den HSL‑Farben

Damit bleiben beliebig viele Emitter gut unterscheidbar, ohne dass du die Farbpalette pflegen musst.

## Bedienung

- Öffne `http://localhost:8000`.
- Links im Panel:
  - Tabelle mit allen aktiven Emitter‑IDs, Frequenz, Pegel und Alter des letzten Eintrags
  - Klick auf eine Zeile: Radar filtert auf genau diesen Emitter
  - Klick erneut bzw. Button „Filter löschen“: Zurück zu allen Pulse
  - Live‑Metriken (Pulse‑Zähler, stärkster AoA, Pegel).

- Rechts:
  - Radar‑Canvas mit Animationseffekt (Nachleuchten)
  - Farbige Pulse, deren Position am Kreis den Winkel und deren Abstand den Pegel repräsentiert.

## Integration in externe Systeme

- Externe Radar‑ oder SIGINT‑Systeme können die Pulse im oben genannten JSON‑Format an `255.255.255.255:50050` broadcasten.
- Emitter‑Status‑Daten können an `255.255.255.255:50051` gesendet werden.
- Für andere IPs/Ports musst du in `app.py` die Konstanten `UDP_PULSE_PORT` und `UDP_EMITTER_PORT` anpassen.

## Entwicklungshinweise

- Backend: `app.py` (Flask + Threading + UDP‑Listener + SSE)
- Frontend: `templates/radar-pulse-view.html` (komplett in einem Template, inkl. Canvas und JS)
- JS‑Logik: komplett im `<script>`‑Block; alle Farben, Filter und Rendering sind dort implementiert.
