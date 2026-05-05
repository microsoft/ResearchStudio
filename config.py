import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
OPENREVIEW_USERNAME = os.getenv("OPENREVIEW_USERNAME", "")
OPENREVIEW_PASSWORD = os.getenv("OPENREVIEW_PASSWORD", "")

# 数据配置
TARGET_CONFERENCES = {
    "ICLR": {
        "years": list(range(2020, 2026)),
        "venue_ids": {
            2020: "ICLR.cc/2020/Conference",
            2021: "ICLR.cc/2021/Conference",
            2022: "ICLR.cc/2022/Conference",
            2023: "ICLR.cc/2023/Conference",
            2024: "ICLR.cc/2024/Conference",
            2025: "ICLR.cc/2025/Conference",
        },
    },
    "NeurIPS": {
        "years": [2023, 2024, 2025],
        "venue_ids": {
            2023: "NeurIPS.cc/2023/Conference",
            2024: "NeurIPS.cc/2024/Conference",
            2025: "NeurIPS.cc/2025/Conference",
        },
    },
    "ICML": {
        "years": [2023, 2024, 2025],
        "venue_ids": {
            2023: "ICML.cc/2023/Conference",
            2024: "ICML.cc/2024/Conference",
            2025: "ICML.cc/2025/Conference",
        },
    },
}

# Venue string patterns for each decision type (API v2 format)
# These vary by conference and year; we match substring
DECISION_VENUE_PATTERNS = {
    "Oral": ["oral"],
    "Spotlight": ["spotlight"],
    "Poster": ["poster"],
    "Rejected": ["Submitted to"],  # Papers that remain "Submitted to X" are rejected
    "Withdrawn": ["Withdrawn"],
    "Desk Rejected": ["Desk Rejected"],
}

# 路径配置
DATA_DIR = "data"
RAW_DIR = f"{DATA_DIR}/raw"
FILTERED_DIR = f"{DATA_DIR}/filtered"
PATTERNS_DIR = f"{DATA_DIR}/patterns"
FULLTEXT_DIR = f"{DATA_DIR}/fulltext"
SKILLS_DIR = "skills"
CHROMA_DIR = "chroma_db"

MAX_TOKENS = 4096

BATCH_SIZE = 10
