"""Deployment settings shared by the app and storage modules."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def get_setting(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    import streamlit as st
    try:
        return str(st.secrets.get(name, default))
    except FileNotFoundError:
        return default


DATA_DIR = Path(get_setting("DATA_DIR", str(BASE_DIR))).expanduser().resolve()
DATABASE_DIR = DATA_DIR / "database"
RESULTS_DIR = DATA_DIR / "results"
DB_PATH = DATABASE_DIR / "transport_cache.db"
