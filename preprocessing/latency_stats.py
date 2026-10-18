from pathlib import Path
import pandas as pd

res = Path(__file__).resolve().parent.parent / "results"
files = sorted(res.glob("latency*.csv"))
if not files:
    raise SystemExit("Chưa có file latency*.csv trong results")

df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
s = df["db_ms"]
print(f"Số mẫu: {len(s)}")
print(f"Trung bình: {s.mean():.0f} ms")
print(f"Trung vị:   {s.median():.0f} ms")
print(f"p95:        {s.quantile(0.95):.0f} ms")
print(f"Nhỏ nhất:   {s.min():.0f} ms")
print(f"Lớn nhất:   {s.max():.0f} ms")