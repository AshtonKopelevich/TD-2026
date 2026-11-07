import pandas as pd

daily = pd.read_parquet("dashboard-royale-main/data/1_prepared_views/prepared_daily_view.parquet")
print(daily.shape)   # (56110, 44): one row per machine per day
print(daily.head())