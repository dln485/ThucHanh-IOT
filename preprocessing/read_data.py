import configparser
from pathlib import Path

from influxdb_client_3 import InfluxDBClient3

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.ini"
cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH, encoding="utf-8")

client = InfluxDBClient3(
    host=cfg["influxdb"]["url"],
    token=cfg["influxdb"]["read_token"],
    database=cfg["influxdb"]["bucket"],
)

sql = """
SELECT time, temperature, humidity, distance_cm, rssi, sequence
FROM sensor_telemetry
WHERE time >= now() - interval '1 hour'
ORDER BY time ASC
"""

df = client.query(sql, mode="pandas")
print("Số dòng:", len(df))
print(df.head())
print(df.dtypes)