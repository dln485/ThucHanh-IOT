# BTL IoT: Thu thập, lưu trữ và tiền xử lý dữ liệu cảm biến

## 1. Kiến trúc hệ thống

```
ESP32 + DHT22 + HC-SR04 (Wokwi)
        │  JSON qua MQTT over TLS (cổng 8883)
        ▼
EMQX Cloud (topic: iot/thuchanh2/telemetry)
        │
        ▼
Python Collector (validate, loại trùng, ghi DB)
        │
        ▼
InfluxDB Cloud Serverless (bucket: iot_sensors)
        │
        ▼
Tiền xử lý (Pandas / NumPy / scikit-learn) ──► measurement sensor_processed
        │
        ▼
Dashboard Streamlit
```

Không dùng Docker và ThingsBoard.

## 2. Cấu trúc thư mục

| Thư mục / file | Nội dung |
|---|---|
| `firmware/` | Code ESP32 (`sketch.ino`), chứng chỉ CA, sơ đồ mạch Wokwi (`diagram.json`), `libraries.txt` |
| `collector/mqtt_collector.py` | Subscribe MQTT, kiểm tra dữ liệu, loại bản tin trùng, ghi InfluxDB, ghi độ trễ ghi |
| `preprocessing/read_data.py` | Kiểm tra đọc dữ liệu từ InfluxDB vào Pandas |
| `preprocessing/preprocess.py` | Tiền xử lý và ghi kết quả vào `sensor_processed` |
| `preprocessing/latency_stats.py` | Thống kê độ trễ ghi từ `results/latency.csv` |
| `dashboard/app.py` | Dashboard Streamlit |
| `config/config.example.ini` | File cấu hình mẫu |
| `results/` | File kết quả (CSV) |

## 3. Yêu cầu

- Python 3.10 trở lên (đã thử với 3.13, bản 64-bit; `pyarrow` không cài được trên Python 32-bit)
- Tài khoản EMQX Cloud (MQTT broker) và InfluxDB Cloud Serverless
- Tài khoản Wokwi để chạy mô phỏng ESP32 (hoặc board ESP32 thật)

## 4. Cài đặt

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 5. Cấu hình

1. Copy `config/config.example.ini` thành `config/config.ini`.
2. Điền thông tin của bạn:
   - EMQX: host, username, password (topic giữ nguyên `iot/thuchanh2/telemetry`)
   - InfluxDB: `url` (chỉ gồm `https://` và tên miền region, không thêm đường dẫn), `org`, `bucket`, `token` (quyền Write), `read_token` (quyền Read)
3. File `config.ini` đã nằm trong `.gitignore`, **không đưa lên GitHub**.

## 6. Thứ tự chạy

**Bước 1. Firmware.** Mở `firmware/sketch.ino` trong Wokwi (hoặc nạp vào ESP32). Điền Wi-Fi, username và password MQTT trong code, nạp chứng chỉ CA `ca_cert.h`. ESP32 gửi JSON mỗi 5 giây:

```json
{"temperature":33.10,"humidity":75.00,"distance_cm":100.86,
 "rssi":-84,"sequence":6,"uptime_s":38,"ts_ms":1792295983000}
```

**Bước 2. Collector** (giữ cửa sổ này mở):

```powershell
python .\collector\mqtt_collector.py
```

**Bước 3. Kiểm tra đọc dữ liệu:**

```powershell
python .\preprocessing\read_data.py
```

**Bước 4. Tiền xử lý:**

```powershell
python .\preprocessing\preprocess.py
```

**Bước 5. Dashboard** (phải chạy bằng lệnh `streamlit run`, không chạy bằng nút Run của editor):

```powershell
streamlit run .\dashboard\app.py
```

Mở `http://localhost:8501`.

**Bước 6. Thống kê độ trễ ghi:**

```powershell
python .\preprocessing\latency_stats.py
```

## 7. Schema InfluxDB

| Measurement | Tag | Field |
|---|---|---|
| `sensor_telemetry` (dữ liệu thô) | `device` | `temperature`, `humidity`, `distance_cm`, `rssi`, `sequence`, `uptime_s` |
| `sensor_processed` (đã xử lý) | `device` | `temperature`, `humidity`, `distance_cm`, `rssi`, `*_roll`, `*_delta`, `*_norm` |

Timestamp của dữ liệu thô là giờ lúc Collector nhận bản tin.

## 8. Retention, trùng lặp và mất dữ liệu

- **Retention:** bucket `iot_sensors` giữ dữ liệu 30 ngày.
- **Mất dữ liệu:** phát hiện bằng cột `sequence` (nhảy số nghĩa là mất bản tin).
- **Trùng lặp:** Collector nhớ 200 bản tin gần nhất theo bộ ba (`sequence`, `uptime_s`, `ts_ms`) và bỏ qua bản tin giao lại.
- **Validate:** kiểm tra đủ trường, đúng kiểu và nằm trong khoảng hợp lệ của cảm biến trước khi ghi.

## 9. Tiền xử lý

1. Đọc dữ liệu theo khoảng thời gian, loại trùng timestamp
2. Phát hiện outlier bằng Z-score cục bộ (trung vị và MAD, cửa sổ 5 bản tin, ngưỡng 3.5)
3. Resample cửa sổ 30 giây
4. Nội suy giá trị thiếu theo thời gian (tối đa 4 cửa sổ liên tiếp)
5. Rolling mean (cửa sổ 5) và delta
6. Chuẩn hóa Min-Max
7. Lưu `results/processed.csv` và ghi vào measurement `sensor_processed`

## 10. Độ trễ

- Độ trễ ghi vào InfluxDB (đo trong Collector): trung bình khoảng 300 ms, trung vị khoảng 288 ms.
- Độ trễ mạng và độ trễ tổng (end-to-end) **chưa đo được chính xác trên Wokwi**, vì đồng hồ ESP32 mô phỏng chạy chậm hơn giờ thật nên chênh lệch thời gian cứ dãn ra. Với ESP32 thật đồng bộ NTP, trường `ts_ms` trong bản tin dùng để đo được.

## 11. Ảnh minh họa

docs/dashboard.jpg
