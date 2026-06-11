"""
SmartNode - Main Application
Runs on Raspberry Pi 4. Serves:
  - Ad Player  -> http://<pi-ip>:5000/player
  - Dashboard  -> http://<pi-ip>:5000/dashboard
  - Sensor API -> http://<pi-ip>:5000/api/sensors

DEV MODE: If real sensor hardware isn't connected (GPIO_AVAILABLE=False),
the app automatically falls back to SIMULATED sensor data so you can
build and test the dashboard/ad-player on ANY machine (your laptop too),
then deploy the same code to the Pi where it will read real sensors.
"""

import os
import time
import json
import random
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template, send_from_directory
from flask_socketio import SocketIO

# ----------------------------------------------------------------------
# Try to import real GPIO / sensor libraries. If unavailable (e.g. running
# on your laptop, not the Pi), fall back to simulation mode automatically.
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADS_DIR = os.path.join(BASE_DIR, "..", "ad-player", "ads")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "smartnode-dev"
socketio = SocketIO(app, cors_allowed_origins="*")

# ----------------------------------------------------------------------
# SENSOR DEFINITIONS
# Each sensor: id, name, category, gpio pin / interface, unit, sim range
# ----------------------------------------------------------------------
SENSORS = [
    {"id": "door1", "name": "Main Door Reed Switch", "model": "Honeywell 2450SN",
     "category": "security", "interface": "GPIO11", "type": "digital", "unit": "open/closed"},
    {"id": "door2", "name": "Service Panel Reed Switch", "model": "Honeywell 2450SN",
     "category": "security", "interface": "GPIO13", "type": "digital", "unit": "open/closed"},
    {"id": "vibration", "name": "Vibration / Tamper Sensor", "model": "SW-420",
     "category": "security", "interface": "GPIO15", "type": "digital", "unit": "triggered/normal"},
    {"id": "panic", "name": "Emergency Button", "model": "Schneider ZB4BH05",
     "category": "security", "interface": "GPIO33", "type": "digital", "unit": "pressed/idle"},
    {"id": "ir_tamper", "name": "Internal Enclosure Tamper", "model": "Omron SS-5GL",
     "category": "security", "interface": "GPIO16", "type": "digital", "unit": "open/closed"},

    {"id": "tof", "name": "Dwell Time (ToF)", "model": "VL53L0X",
     "category": "analytics", "interface": "I2C 0x29", "type": "analog", "unit": "mm", "sim_range": [50, 2000]},
    {"id": "ir_counter", "name": "Footfall IR Beam Counter", "model": "TCRT5000",
     "category": "analytics", "interface": "GPIO18", "type": "counter", "unit": "people"},
    {"id": "radar", "name": "Approach Radar", "model": "HLK-LD2410",
     "category": "analytics", "interface": "UART", "type": "digital", "unit": "presence/none"},
    {"id": "wifi_mac", "name": "WiFi MAC Counter", "model": "Alfa AWUS036ACH",
     "category": "analytics", "interface": "USB", "type": "counter", "unit": "devices"},
    {"id": "ble_scan", "name": "BLE Proximity Scanner", "model": "Nordic nRF52840",
     "category": "analytics", "interface": "USB", "type": "counter", "unit": "devices"},

    {"id": "power", "name": "Electricity Meter", "model": "PZEM-004T V3.0",
     "category": "operations", "interface": "UART6", "type": "analog", "unit": "W", "sim_range": [40, 180]},
    {"id": "sound", "name": "Sound Level (Mic)", "model": "ADMP401 + MCP3008",
     "category": "operations", "interface": "SPI", "type": "analog", "unit": "dB", "sim_range": [30, 90]},

    {"id": "rtc", "name": "Real Time Clock", "model": "DS3231",
     "category": "infrastructure", "interface": "I2C 0x68", "type": "clock", "unit": "datetime"},
    {"id": "temp", "name": "Enclosure Temperature", "model": "DS18B20",
     "category": "infrastructure", "interface": "1-Wire GPIO7", "type": "analog", "unit": "°C", "sim_range": [25, 65]},
]

# Live state - updated by background thread
sensor_state = {s["id"]: {"value": None, "status": "unknown", "last_update": None} for s in SENSORS}

# Counters that accumulate
footfall_total = 0
ble_total = 0
wifi_total = 0


# ----------------------------------------------------------------------
# SENSOR READING - REAL (Pi/GPIO) vs SIMULATED
# ----------------------------------------------------------------------
def read_sensor_real(sensor):
    """
    Placeholder for real sensor reading on the Pi.
    Fill these in one sensor at a time as you wire each one up.
    For now returns None -> falls back to simulation for unwired sensors.
    """
    # TODO: Implement per-sensor real reads as you wire them up.
    # Example for a digital GPIO sensor:
    #
    # if sensor["id"] == "door1":
    #     return "closed" if GPIO.input(11) else "open"
    #
    # Example for DS18B20 (1-Wire temp):
    #
    # if sensor["id"] == "temp":
    #     with open("/sys/bus/w1/devices/28-XXXX/w1_slave") as f:
    #         data = f.read()
    #     temp_c = float(data.split("t=")[-1]) / 1000.0
    #     return round(temp_c, 1)
    return None


def read_sensor_simulated(sensor):
    """Generate realistic fake data so the dashboard is fully testable
    on your laptop, before any hardware is wired."""
    global footfall_total, ble_total, wifi_total

    if sensor["type"] == "digital":
        # Mostly normal, occasionally trigger
        return random.choices(["normal", "triggered"], weights=[97, 3])[0] \
            if sensor["id"] != "panic" \
            else random.choices(["idle", "pressed"], weights=[995, 5])[0]

    if sensor["type"] == "analog":
        lo, hi = sensor["sim_range"]
        return round(random.uniform(lo, hi), 1)

    if sensor["type"] == "counter":
        increment = random.choice([0, 0, 0, 1, 1, 2])
        if sensor["id"] == "ir_counter":
            footfall_total += increment
            return footfall_total
        if sensor["id"] == "ble_scan":
            ble_total += increment
            return ble_total
        if sensor["id"] == "wifi_mac":
            wifi_total += increment
            return wifi_total

    if sensor["type"] == "clock":
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return None


def sensor_loop():
    """Background thread: reads all sensors every 2 seconds and pushes
    updates to connected dashboards via WebSocket."""
    while True:
        for sensor in SENSORS:
            value = None
            if GPIO_AVAILABLE:
                value = read_sensor_real(sensor)
            if value is None:
                value = read_sensor_simulated(sensor)

            sensor_state[sensor["id"]] = {
                "value": value,
                "status": "live" if GPIO_AVAILABLE else "simulated",
                "last_update": datetime.now().strftime("%H:%M:%S"),
            }

        socketio.emit("sensor_update", sensor_state)
        time.sleep(2)


# ----------------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/player")
def player():
    """Fullscreen ad player. Open this in Chromium kiosk mode on the
    32" display: chromium-browser --kiosk http://localhost:5000/player"""
    ads = []
    if os.path.isdir(ADS_DIR):
        ads = [f for f in os.listdir(ADS_DIR)
               if f.lower().endswith((".jpg", ".jpeg", ".png", ".mp4", ".webm", ".gif"))]
    return render_template("player.html", ads=ads)


@app.route("/ads/<path:filename>")
def serve_ad(filename):
    return send_from_directory(ADS_DIR, filename)


@app.route("/dashboard")
def dashboard():
    """Live sensor dashboard. Open on phone/laptop, or split-screen
    alongside the ad player."""
    return render_template("dashboard.html", sensors=SENSORS,
                            mode="LIVE (GPIO)" if GPIO_AVAILABLE else "SIMULATED")


@app.route("/api/sensors")
def api_sensors():
    """JSON snapshot of all sensor states - useful for testing/integration."""
    return jsonify({
        "mode": "live" if GPIO_AVAILABLE else "simulated",
        "timestamp": datetime.now().isoformat(),
        "sensors": [
            {**s, **sensor_state[s["id"]]} for s in SENSORS
        ]
    })


@app.route("/api/sensors/<category>")
def api_sensors_by_category(category):
    filtered = [
        {**s, **sensor_state[s["id"]]} for s in SENSORS if s["category"] == category
    ]
    return jsonify(filtered)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("SmartNode Server Starting")
    print(f"Mode: {'LIVE GPIO (Raspberry Pi)' if GPIO_AVAILABLE else 'SIMULATED (dev machine)'}")
    print("=" * 60)
    print("Ad Player  -> http://localhost:5000/player")
    print("Dashboard  -> http://localhost:5000/dashboard")
    print("Sensor API -> http://localhost:5000/api/sensors")
    print("=" * 60)

    if GPIO_AVAILABLE:
        GPIO.setmode(GPIO.BOARD)
        # TODO: GPIO.setup() calls go here as you wire each sensor

    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
