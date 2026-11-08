import duckdb
import pandas as pd

duckdb.sql("SELECT * FROM read_parquet('dashboard-royale-main/data/2_machine_decision/game_math.parquet')").show()