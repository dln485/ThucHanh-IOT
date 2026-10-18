import csv
import json
import time
import configparser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# ---------- Đọc cấu hình ----------
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.ini"
cfg = configparser.ConfigParser()
if not cfg.read(CONFIG_PATH, encoding="utf-8"):
    raise SystemExit(f"Không đọc được file cấu hình: {CONFIG_PATH}")

MQTT_HOST = cfg["mqtt"]["host"]
MQTT_PORT = int(cfg["mqtt"]["port"])
MQTT_USER = cfg["mqtt"]["username"]
MQTT_PASS = cfg["mqtt"]["password"]
MQTT_TOPIC = cfg["mqtt"]["topic"]

INFLUX_URL = cfg["influxdb"]["url"]
INFLUX_ORG = cfg["influxdb"]["org"]
INFLUX_BUCKET = cfg["influxdb"]["bucket"]
INFLUX_TOKEN = cfg["influxdb"]["token"]

DEVICE_ID = "esp32-01"

# ---------- File ghi độ trễ ----------
LAT_CSV = CONFIG_PATH.parent.parent / "results" / "latency.csv"
LAT_CSV.parent.mkdir(exist_ok=True)
if not LAT_CSV.exists():
    with open(LAT_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            ["sequence", "ts_sent_ms", "ts_recv_ms", "ts_done_ms",
             "net_ms", "db_ms", "total_ms"]
        )

# ---------- Kết nối InfluxDB ----------
influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

# ---------- Kiểm tra dữ liệu ----------
RULES = [
    ("temperature", float, -40.0, 80.0),
    ("humidity", float, 0.0, 100.0),
    ("distance_cm", float, 0.0, 450.0),
    ("rssi", int, -120, 0),
    ("sequence", int, 0, 10**9),
    ("uptime_s", int, 0, 10**9),
]


def validate(data):
    """Trả về (dict hợp lệ, None) hoặc (None, lý do lỗi)."""
    if not isinstance(data, dict):
        return None, "payload không phải JSON object"
    clean = {}
    for name, typ, lo, hi in RULES:
        if name not in data:
            return None, f"thiếu trường '{name}'"
        try:
            value = typ(data[name])
        except (TypeError, ValueError):
            return None, f"trường '{name}' sai kiểu: {data[name]!r}"
        if not (lo <= value <= hi):
            return None, f"trường '{name}' ngoài khoảng [{lo}, {hi}]: {value}"
        clean[name] = value
    return clean, None


# Nhớ 200 bản tin gần nhất để loại bản tin bị giao lại (trùng)
recent = deque(maxlen=200)


# ---------- Callback MQTT (chạy được với paho 1.x và 2.x) ----------
def on_connect(client, userdata, flags, rc, properties=None):
    failed = getattr(rc, "is_failure", None)
    ok = (not failed) if failed is not None else (rc == 0)
    if ok:
        print(f"[MQTT] Đã kết nối EMQX, subscribe: {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC, qos=1)
    else:
        print(f"[MQTT] Kết nối thất bại, mã lỗi: {rc}")


def on_disconnect(client, userdata, *args):
    print("[MQTT] Mất kết nối, thư viện sẽ tự thử kết nối lại...")


def on_message(client, userdata, msg):
    t_recv_ms = time.time() * 1000          # mốc: Collector nhận được bản tin

    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(f"[BỎ QUA] Không phải JSON: {msg.payload[:80]!r}")
        return

    clean, error = validate(data)
    if error:
        print(f"[BỎ QUA] {error} | {data}")
        return

    # Loại bản tin trùng (giao lại): gán khóa TRƯỚC, kiểm tra SAU
    dedup_key = (clean["sequence"], clean["uptime_s"], data.get("ts_ms"))
    if dedup_key in recent:
        print(f"[TRÙNG] seq={clean['sequence']} đã ghi rồi, bỏ qua")
        return
    recent.append(dedup_key)

    now = datetime.now(timezone.utc)
    point = (
        Point("sensor_telemetry")
        .tag("device", DEVICE_ID)
        .time(now, WritePrecision.NS)
    )
    for field_name, field_value in clean.items():
        point = point.field(field_name, field_value)

    try:
        t_w0 = time.time() * 1000
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        t_done_ms = time.time() * 1000      # mốc: InfluxDB ghi xong
    except Exception as e:
        print(f"[LỖI GHI INFLUXDB] {e}")
        return

    msg_line = (f"[GHI OK] seq={clean['sequence']} "
                f"T={clean['temperature']}°C H={clean['humidity']}% "
                f"D={clean['distance_cm']}cm")

    # Tính độ trễ nếu bản tin có ts_ms
    ts_sent = data.get("ts_ms")
    if isinstance(ts_sent, (int, float)) and ts_sent > 0:
        net_ms = t_recv_ms - ts_sent
        db_ms = t_done_ms - t_w0
        total_ms = t_done_ms - ts_sent
        with open(LAT_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [clean["sequence"], int(ts_sent), int(t_recv_ms), int(t_done_ms),
                 round(net_ms, 1), round(db_ms, 1), round(total_ms, 1)]
            )
        msg_line += f" | db={db_ms:.0f}ms"

    print(msg_line)


# ---------- Khởi động ----------
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho 2.x
except AttributeError:
    client = mqtt.Client()  # paho 1.x

client.username_pw_set(MQTT_USER, MQTT_PASS)
client.tls_set()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.reconnect_delay_set(min_delay=1, max_delay=30)

print(f"[MQTT] Đang kết nối {MQTT_HOST}:{MQTT_PORT} ...")
client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\nĐã dừng Collector.")
finally:
    client.disconnect()
    influx.close()