import configparser
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from influxdb_client_3 import InfluxDBClient3
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

# ---------- Tham số ----------
HOURS = 24            # đọc dữ liệu trong N giờ gần nhất
RESAMPLE = "30s"      # cửa sổ resampling (dữ liệu ít nên dùng 30 giây)
ROLL_WINDOW = 5       # số cửa sổ cho rolling mean
IQR_K = 1.5           # hệ số IQR
COLS = ["temperature", "humidity", "distance_cm"]
OUT_MEASUREMENT = "sensor_processed"
DEVICE_ID = "esp32-01"

BASE = Path(__file__).resolve().parent.parent
cfg = configparser.ConfigParser()
cfg.read(BASE / "config" / "config.ini", encoding="utf-8")
url = cfg["influxdb"]["url"]
org = cfg["influxdb"]["org"]
bucket = cfg["influxdb"]["bucket"]

# ---------- 1. Đọc dữ liệu ----------
reader = InfluxDBClient3(host=url, token=cfg["influxdb"]["read_token"], database=bucket)
sql = f"""
SELECT time, temperature, humidity, distance_cm, rssi, sequence
FROM sensor_telemetry
WHERE time >= now() - interval '{HOURS} hours'
ORDER BY time ASC
"""
df = reader.query(sql, mode="pandas")
print(f"[1] Đọc được {len(df)} dòng")

df["time"] = pd.to_datetime(df["time"])
df = df.drop_duplicates(subset="time").set_index("time").sort_index()

# ---------- 2. Bản tin bị mất (dựa vào sequence) ----------
gap = df["sequence"].diff()
lost = int((gap[gap > 1] - 1).sum())
print(f"[2] Số bản tin bị mất (theo sequence): {lost}")

# ---------- 3. Outlier bằng Z-score cục bộ (trung vị + MAD) ----------
WIN = 5       # cửa sổ 11 bản tin (~55 giây)
Z_THR = 3.5    # ngưỡng
MIN_SCALE = {"temperature": 0.5, "humidity": 2.0, "distance_cm": 2.0}  # độ nhiễu tối thiểu

flag = pd.DataFrame(index=df.index)
for c in COLS:
    med = df[c].rolling(WIN, center=True, min_periods=3).median()
    mad = (df[c] - med).abs().rolling(WIN, center=True, min_periods=3).median()
    scale = np.maximum(1.4826 * mad, MIN_SCALE[c])
    z = (df[c] - med).abs() / scale
    flag[c] = z > Z_THR
    print(f"[3] {c}: outlier = {int(flag[c].sum())}")
    if flag[c].any():
        print(df.loc[flag[c], [c]].head(10))
    df.loc[flag[c], c] = np.nan   # đánh dấu thiếu, sẽ được nội suy
# ---------- 4. Resampling ----------
agg = {c: "mean" for c in COLS}
agg["rssi"] = "mean"
rs = df.resample(RESAMPLE).agg(agg)
print(f"[4] Sau resample {RESAMPLE}: {len(rs)} dòng, thiếu {int(rs[COLS].isna().any(axis=1).sum())} dòng")

# ---------- 5. Giá trị thiếu: nội suy theo thời gian ----------
rs[COLS + ["rssi"]] = rs[COLS + ["rssi"]].interpolate(method="time", limit=4)
rs = rs.dropna(subset=COLS)   # khoảng trống quá dài thì bỏ
print(f"[5] Sau xử lý thiếu: {len(rs)} dòng")

# ---------- 6. Đặc trưng ----------
for c in COLS:
    rs[f"{c}_roll"] = rs[c].rolling(ROLL_WINDOW, min_periods=1).mean()
    rs[f"{c}_delta"] = rs[c].diff().fillna(0)

# ---------- 7. Chuẩn hóa Min-Max ----------
scaler = MinMaxScaler()
norm = scaler.fit_transform(rs[COLS])
for i, c in enumerate(COLS):
    rs[f"{c}_norm"] = norm[:, i]

print(rs.head(10))

# ---------- 8. Lưu CSV ----------
out_dir = BASE / "results"
out_dir.mkdir(exist_ok=True)
rs.to_csv(out_dir / "processed.csv")
print(f"[8] Đã lưu {out_dir / 'processed.csv'}")

# ---------- 9. Ghi vào measurement mới ----------
writer = InfluxDBClient(url=url, token=cfg["influxdb"]["token"], org=org)
write_api = writer.write_api(write_options=SYNCHRONOUS)
points = []
for ts, row in rs.iterrows():
    p = Point(OUT_MEASUREMENT).tag("device", DEVICE_ID).time(
        ts.tz_localize("UTC").to_pydatetime(), WritePrecision.NS)
    for col, val in row.items():
        if pd.notna(val):
            p = p.field(col, float(val))
    points.append(p)
write_api.write(bucket=bucket, org=org, record=points)
print(f"[9] Đã ghi {len(points)} điểm vào measurement '{OUT_MEASUREMENT}'")
writer.close()