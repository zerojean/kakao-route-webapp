"""SQLite 영구 캐시 관리 모듈."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from settings import DATABASE_DIR, DB_PATH


def _connect() -> sqlite3.Connection:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialize_database() -> None:
    """캐시 DB와 필요한 테이블을 생성한다."""
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS address_cache (
                cache_key TEXT PRIMARY KEY,
                query_address TEXT NOT NULL,
                matched_address TEXT NOT NULL,
                search_query TEXT NOT NULL,
                cleaning_step TEXT NOT NULL,
                coordinate_status TEXT NOT NULL,
                longitude REAL NOT NULL,
                latitude REAL NOT NULL,
                coordinate_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS route_cache (
                origin_lon REAL NOT NULL,
                origin_lat REAL NOT NULL,
                destination_lon REAL NOT NULL,
                destination_lat REAL NOT NULL,
                car_type INTEGER NOT NULL,
                distance_m REAL NOT NULL,
                duration_s REAL NOT NULL,
                toll_won INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    origin_lon,
                    origin_lat,
                    destination_lon,
                    destination_lat,
                    car_type
                )
            );
            """
        )


def get_address_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT query_address, matched_address, search_query,
                   cleaning_step, coordinate_status, longitude,
                   latitude, coordinate_note
            FROM address_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()

    return dict(row) if row else None


def save_address_cache(cache_key: str, result: Dict[str, Any]) -> None:
    """성공한 주소 좌표 결과만 영구 저장한다."""
    longitude = result.get("경도")
    latitude = result.get("위도")
    if longitude is None or latitude is None:
        return

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO address_cache (
                cache_key, query_address, matched_address, search_query,
                cleaning_step, coordinate_status, longitude, latitude,
                coordinate_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                query_address = excluded.query_address,
                matched_address = excluded.matched_address,
                search_query = excluded.search_query,
                cleaning_step = excluded.cleaning_step,
                coordinate_status = excluded.coordinate_status,
                longitude = excluded.longitude,
                latitude = excluded.latitude,
                coordinate_note = excluded.coordinate_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                str(result.get("원본주소", "")),
                str(result.get("조회주소", "")),
                str(result.get("API검색어", "")),
                str(result.get("정제단계", "")),
                str(result.get("좌표상태", "")),
                float(longitude),
                float(latitude),
                str(result.get("좌표메모", "")),
            ),
        )


def get_route_cache(
    origin_lon: float,
    origin_lat: float,
    destination_lon: float,
    destination_lat: float,
    car_type: int,
) -> Optional[Tuple[float, float, int]]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT distance_m, duration_s, toll_won
            FROM route_cache
            WHERE origin_lon = ? AND origin_lat = ?
              AND destination_lon = ? AND destination_lat = ?
              AND car_type = ?
            """,
            (
                origin_lon,
                origin_lat,
                destination_lon,
                destination_lat,
                car_type,
            ),
        ).fetchone()

    if not row:
        return None
    return float(row["distance_m"]), float(row["duration_s"]), int(row["toll_won"])


def save_route_cache(
    origin_lon: float,
    origin_lat: float,
    destination_lon: float,
    destination_lat: float,
    car_type: int,
    distance_m: float,
    duration_s: float,
    toll_won: int,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO route_cache (
                origin_lon, origin_lat, destination_lon, destination_lat,
                car_type, distance_m, duration_s, toll_won
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                origin_lon, origin_lat, destination_lon,
                destination_lat, car_type
            ) DO UPDATE SET
                distance_m = excluded.distance_m,
                duration_s = excluded.duration_s,
                toll_won = excluded.toll_won,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                origin_lon,
                origin_lat,
                destination_lon,
                destination_lat,
                car_type,
                distance_m,
                duration_s,
                toll_won,
            ),
        )


def get_cache_counts() -> Dict[str, int]:
    with _connect() as connection:
        address_count = connection.execute(
            "SELECT COUNT(*) FROM address_cache"
        ).fetchone()[0]
        route_count = connection.execute(
            "SELECT COUNT(*) FROM route_cache"
        ).fetchone()[0]
    return {"address": int(address_count), "route": int(route_count)}


def clear_cache(cache_type: str) -> None:
    table_map = {
        "address": "address_cache",
        "route": "route_cache",
        "all": None,
    }
    if cache_type not in table_map:
        raise ValueError("cache_type은 address, route, all 중 하나여야 합니다.")

    with _connect() as connection:
        if cache_type == "all":
            connection.execute("DELETE FROM address_cache")
            connection.execute("DELETE FROM route_cache")
        else:
            connection.execute(f"DELETE FROM {table_map[cache_type]}")


initialize_database()
