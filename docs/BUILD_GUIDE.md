# SmartNode Build Guide — Phase by Phase

## Architecture Recap
- **Pi 4** runs `sensor-service/app.py` (Flask + SocketIO)
- `/player` → fullscreen ad loop (32" display, Chromium kiosk mode)
- `/dashboard` → live sensor readings (phone/laptop, or split-screen)
- Code runs in **SIMULATED mode** automatically on any machine without GPIO
  (your laptop) — switches to **LIVE mode** automatically on the Pi once
  `RPi.GPIO` is available and sensors are wired.

This means: **you can test the dashboard/UI right now on your laptop**,
then deploy the identical code to the Pi and wire sensors one at a time.

---

## PHASE 0 — Display Check (Pi + 32" screen)
1. Connect Pi 4 → 32" display via **HDMI0** (port closest to USB-C power)
2. Power on. If no signal:
   - Edit `/boot/firmware/config.txt`, add:
     ```
     hdmi_force_hotplug=1
     hdmi_group=1
     hdmi_mode=16
     ```
   - Reboot
3. YouTube: search **"Raspberry Pi 4 HDMI no signal fix config.txt"**

---

## PHASE 1 — Run the App (Laptop, today)
```bash
cd smartnode/sensor-service
pip install -r requirements.txt
python3 app.py
```
Open:
- `http://localhost:5000` — control panel
- `http://localhost:5000/player` — ad player (drop files into `ad-player/ads/`)
- `http://localhost:5000/dashboard` — live sensor dashboard (simulated data)

This proves the whole pipeline works end-to-end before touching hardware.

---

## PHASE 2 — Deploy to Pi (same code, now with real sensors)
```bash
# On Pi:
sudo apt install python3-pip python3-rpi.gpio
git clone <your-repo>   # or copy folder via USB/SCP
cd smartnode/sensor-service
pip install -r requirements.txt
python3 app.py
```
On the Pi, `RPi.GPIO` will import successfully → mode becomes **LIVE**.
Sensors not yet wired will still show simulated values until you implement
their `read_sensor_real()` block (see app.py — clearly marked TODOs).

For kiosk display:
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:5000/player
```

---

## PHASE 3 — Wire Sensors ONE AT A TIME

For each sensor: wire on breadboard → write/test the `read_sensor_real()`
snippet in isolation → confirm reading → integrate into app.py → move on.

### Security Sensors

**1 & 2. Door Reed Switches (Honeywell 2450SN) — GPIO 11, GPIO 13**
- Wiring: one wire to GPIO pin, other to GND. Magnet on door = circuit closed.
- Code:
  ```python
  GPIO.setup(11, GPIO.IN, pull_up_down=GPIO.PUD_UP)
  state = "closed" if GPIO.input(11) == GPIO.LOW else "open"
  ```
- YouTube: **"Raspberry Pi reed switch door sensor GPIO tutorial"**

**3. Vibration Sensor (SW-420) — GPIO 15**
- Has onboard potentiometer to set sensitivity. Digital OUT → GPIO.
- Code:
  ```python
  GPIO.setup(15, GPIO.IN)
  triggered = GPIO.input(15) == GPIO.HIGH
  ```
- YouTube: **"SW-420 vibration sensor Raspberry Pi tutorial"**

**4. Emergency Button (Schneider ZB4BH05) — GPIO 33**
- Normally-open pushbutton. One leg to GPIO, other to GND, use pull-up.
- Code: same pattern as reed switch.
- YouTube: **"Raspberry Pi pushbutton GPIO pull-up tutorial"**

**5. IR Tamper Switch (Omron SS-5GL) — GPIO 16**
- Microswitch, wired same as reed switches.

### Analytics Sensors

**6. ToF Distance Sensor (VL53L0X) — I2C 0x29**
- Enable I2C: `sudo raspi-config` → Interface Options → I2C → Enable
- Install: `pip install adafruit-circuitpython-vl53l0x`
- Code:
  ```python
  import board, adafruit_vl53l0x
  i2c = board.I2C()
  vl53 = adafruit_vl53l0x.VL53L0X(i2c)
  distance_mm = vl53.range
  ```
- YouTube: **"VL53L0X Raspberry Pi I2C distance sensor tutorial"**

**7. IR Beam Counter (TCRT5000) — GPIO 18**
- Digital OUT goes LOW when beam is broken (object detected).
- Code:
  ```python
  GPIO.setup(18, GPIO.IN)
  if GPIO.input(18) == GPIO.LOW:
      footfall_total += 1
  ```
- YouTube: **"TCRT5000 IR sensor Raspberry Pi people counter"**

**8. Approach Radar (HLK-LD2410) — UART**
- Connects via TX/RX to Pi UART pins (GPIO14/15 — note: conflicts with
  some setups, may need to enable a secondary UART or use USB-serial adapter).
- Library: `pip install ld2410`
- YouTube: **"HLK-LD2410 Raspberry Pi UART presence sensor"**

**9. WiFi MAC Counter (Alfa AWUS036ACH) — USB**
- Plug into USB 3.0 port. Requires monitor mode:
  ```bash
  sudo airmon-ng start wlan1
  sudo tcpdump -i wlan1mon -e -s 256 type mgt subtype probe-req
  ```
- Parse MAC addresses from probe requests, dedupe per time window.
- YouTube: **"WiFi probe request sniffing Raspberry Pi footfall counter"**

**10. BLE Scanner (Nordic nRF52840) — USB**
- Use `bleak` library for BLE scanning:
  ```python
  pip install bleak
  ```
- YouTube: **"Python bleak BLE scanner Raspberry Pi tutorial"**

### Operations Sensors

**11. Electricity Meter (PZEM-004T V3.0) — UART6**
- Library: `pip install pzem-004t` (or use `pyserial` directly with Modbus)
- Code:
  ```python
  from pzem import PZEM004Tv30
  meter = PZEM004Tv30('/dev/ttyUSB0')
  power_w = meter.power()
  ```
- YouTube: **"PZEM-004T Raspberry Pi energy monitor tutorial"**

**12. Sound Level (ADMP401 + MCP3008) — SPI**
- Enable SPI: `sudo raspi-config` → Interface Options → SPI → Enable
- MCP3008 is an ADC (Pi has no analog pins) — mic connects to MCP3008
  channel, MCP3008 connects to Pi via SPI.
- Library: `pip install adafruit-circuitpython-mcp3xxx`
- YouTube: **"MCP3008 Raspberry Pi analog sensor SPI tutorial"**

### Infrastructure Sensors

**13. Real Time Clock (DS3231) — I2C 0x68**
- Same I2C bus as VL53L0X. Library: `pip install adafruit-circuitpython-ds3231`
- YouTube: **"DS3231 RTC Raspberry Pi setup tutorial"**

**14. Temperature Probe (DS18B20) — 1-Wire GPIO 7**
- Enable 1-Wire: add `dtoverlay=w1-gpio` to `/boot/firmware/config.txt`, reboot
- Find device: `ls /sys/bus/w1/devices/` → look for `28-xxxxxxxx`
- Code:
  ```python
  with open(f"/sys/bus/w1/devices/{device_id}/w1_slave") as f:
      data = f.read()
  temp_c = float(data.split("t=")[-1]) / 1000.0
  ```
- YouTube: **"DS18B20 Raspberry Pi 1-Wire temperature sensor tutorial"**

---

## PHASE 4 — Integration
Once 2-3 sensors are confirmed working individually, fill in their blocks
in `read_sensor_real()` in `app.py`, restart, confirm dashboard shows
"LIVE" status with real readings instead of simulated.

Repeat sensor-by-sensor until all 14 are live.

---

## PHASE 5 — Demo Day
- Pi running `app.py` on boot (use `systemd` service — ask me to set this up)
- 32" display showing `/player` in kiosk mode
- Phone/tablet showing `/dashboard` for the live walkthrough
- This is your investor/partner demo: "the screen plays ads, and here's
  the live sensor data proving footfall, dwell time, and machine health"
