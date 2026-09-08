from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from settings import DATABASE_DIR, RESULTS_DIR, DB_PATH
from cloud_history import CloudHistory, cloud_enabled


def initialize_result_history() -> None:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS result_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL,
                original_file_name TEXT,
                result_file_name TEXT NOT NULL,
                result_file_path TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def sanitize_file_stem(value: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in value)
    cleaned = " ".join(cleaned.split()).strip(" ._")
    return cleaned or "노선조회결과"


def save_result_file(
    file_bytes: bytes,
    original_file_name: str,
    row_count: int,
    success_count: int,
    failure_count: int,
    job_name: Optional[str] = None,
) -> Dict[str, Any]:
    if cloud_enabled():
        return CloudHistory().save(file_bytes, {
            "job_name": sanitize_file_stem(job_name or Path(original_file_name).stem),
            "original_file_name": original_file_name,
            "result_file_name": sanitize_file_stem(Path(original_file_name).stem) + "_결과.xlsx",
            "row_count": int(row_count), "success_count": int(success_count),
            "failure_count": int(failure_count),
        })
    initialize_result_history()

    from uuid import uuid4
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]
    original_path = Path(original_file_name or "노선조회.xlsx")
    original_stem = sanitize_file_stem(original_path.stem)
    result_file_name = f"{timestamp}_{original_stem}_결과.xlsx"
    result_path = RESULTS_DIR / result_file_name
    result_path.write_bytes(file_bytes)

    display_job_name = sanitize_file_stem(job_name or original_stem)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            """
            INSERT INTO result_history (
                job_name,
                original_file_name,
                result_file_name,
                result_file_path,
                row_count,
                success_count,
                failure_count,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                display_job_name,
                original_file_name,
                result_file_name,
                str(result_path.resolve()),
                int(row_count),
                int(success_count),
                int(failure_count),
                created_at,
            ),
        )
        connection.commit()
        history_id = cursor.lastrowid

    return {
        "id": history_id,
        "job_name": display_job_name,
        "original_file_name": original_file_name,
        "result_file_name": result_file_name,
        "result_file_path": str(result_path.resolve()),
        "row_count": int(row_count),
        "success_count": int(success_count),
        "failure_count": int(failure_count),
        "created_at": created_at,
    }


def get_result_history() -> List[Dict[str, Any]]:
    if cloud_enabled():
        return CloudHistory().list()
    initialize_result_history()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                id,
                job_name,
                original_file_name,
                result_file_name,
                result_file_path,
                row_count,
                success_count,
                failure_count,
                created_at
            FROM result_history
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_result_record(history_id: int) -> Optional[Dict[str, Any]]:
    initialize_result_history()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM result_history WHERE id = ?",
            (int(history_id),),
        ).fetchone()

    return dict(row) if row else None


def delete_result_history(history_id: int, delete_file: bool = True) -> bool:
    if cloud_enabled():
        return CloudHistory().delete(history_id)
    record = get_result_record(history_id)
    if not record:
        return False

    if delete_file:
        path = Path(record["result_file_path"])
        try:
            if path.exists():
                path.unlink()
        except OSError:
            return False

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "DELETE FROM result_history WHERE id = ?",
            (int(history_id),),
        )
        connection.commit()

    return True


def remove_missing_file_records() -> int:
    if cloud_enabled():
        return 0
    removed = 0
    for record in get_result_history():
        if not Path(record["result_file_path"]).exists():
            with sqlite3.connect(DB_PATH) as connection:
                connection.execute(
                    "DELETE FROM result_history WHERE id = ?",
                    (int(record["id"]),),
                )
                connection.commit()
            removed += 1
    return removed


def read_result_file(record):
    if "storage_path" in record:
        return CloudHistory().download(record)
    return Path(record["result_file_path"]).read_bytes()
