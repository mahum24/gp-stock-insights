"""GP Stock Insights: a year of GP practice stock data, modelled for Power BI."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GPSTOCK_DATA_DIR", ROOT / "data"))
