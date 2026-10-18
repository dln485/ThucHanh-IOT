import configparser
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from influxdb_client_3 import InfluxDBClient3

BASE = Path(__file__).resolve().parent.parent
cfg = configparser.ConfigParser()
cfg.read(BASE / "config" / "config.ini", encoding="utf-8")

st.set_page_config(page_title="IoT Dashboard", layout="wide")
st.title("Giám sát cảm biến IoT")

hours = st.sidebar.slider("Khoảng thời gian (giờ)", 1, 24, 6)
sensor = st.sidebar.selectbox("Cảm biến", ["temperature", "humidity", "distance_cm"])
if st.sidebar.button("Làm mới dữ liệu"):
    st.cache_data.clear()


@st.cache_data(ttl=10)
def query(sql):
    client = InfluxDBClient3(
        host=cfg["influxdb"]["url"],
        token=cfg["influxdb"]["read_token"],
        database=cfg["influxdb"]["bucket"],
    )
    return client.query(sql, mode="pandas")


raw = query(f"""
    SELECT time, {sensor} FROM sensor_telemetry
    WHERE time >= now() - interval '{hours} hours' ORDER BY time ASC""")
proc = query(f"""
    SELECT time, {sensor}, {sensor}_roll FROM sensor_processed
    WHERE time >= now() - interval '{hours} hours' ORDER BY time ASC""")

if raw.empty:
    st.warning("Chưa có dữ liệu thô trong khoảng thời gian này.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Giá trị mới nhất", f"{raw[sensor].iloc[-1]:.2f}")
    c2.metric("Số điểm dữ liệu thô", len(raw))
    c3.metric("Số điểm đã xử lý", len(proc))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=raw["time"], y=raw[sensor], mode="markers+lines",
                             name="Dữ liệu thô", opacity=0.5))
    if not proc.empty:
        fig.add_trace(go.Scatter(x=proc["time"], y=proc[sensor],
                                 name="Đã xử lý (resample 30s)"))
        fig.add_trace(go.Scatter(x=proc["time"], y=proc[f"{sensor}_roll"],
                                 name="Rolling mean"))
    fig.update_layout(height=450, xaxis_title="Thời gian", yaxis_title=sensor)
    st.plotly_chart(fig, use_container_width=True)