r"""SQL Server 数据访问层（pyodbc）。

默认连接本机 LocalDB： (localdb)\MSSQLLocalDB
也可以通过 .env 连接正式 SQL Server 实例。
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pyodbc

from . import config

_schema_lock = threading.Lock()
_schema_ready = False


def _connection_string(database: str, *, master: bool = False) -> str:
    parts = [
        f"DRIVER={{{config.DB_DRIVER}}}",
        f"SERVER={config.DB_SERVER}",
        f"DATABASE={database}",
        f"Encrypt={config.DB_ENCRYPT}",
        "TrustServerCertificate=yes",
        f"Connection Timeout={config.DB_TIMEOUT}",
    ]
    if config.DB_TRUSTED:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={config.DB_USER}")
        parts.append(f"PWD={config.DB_PASSWORD}")
    return ";".join(parts) + ";"


def _safe_db_name() -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", config.DB_NAME):
        raise ValueError("DB_NAME 只允许字母、数字和下划线")
    return config.DB_NAME


def connect(database: str | None = None, *, autocommit: bool = False) -> pyodbc.Connection:
    name = database or _safe_db_name()
    conn = pyodbc.connect(_connection_string(name), autocommit=autocommit, timeout=config.DB_TIMEOUT)
    return conn


def ensure_database() -> None:
    """首次启动时自动创建数据库、表结构与种子数据。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        db_name = _safe_db_name()
        master = connect("master", autocommit=True)
        try:
            cur = master.cursor()
            exists = cur.execute("SELECT DB_ID(?)", db_name).fetchone()[0]
            if not exists:
                create_database(cur, db_name)
        finally:
            master.close()

        schema_path = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
        script = schema_path.read_text(encoding="utf-8")
        conn = connect(db_name)
        try:
            execute_script(conn, script)
            conn.commit()
        finally:
            conn.close()
        _schema_ready = True


def _sql_path(value: Path) -> str:
    return str(value).replace("'", "''")


def create_database(cur: pyodbc.Cursor, db_name: str, data_dir: Path | None = None) -> None:
    """新装数据库文件放到项目 database/mssql；失败时回退 LocalDB 默认目录。"""
    directory = Path(data_dir or config.DB_DATA_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    mdf = directory / f"{db_name}.mdf"
    ldf = directory / f"{db_name}_log.ldf"
    try:
        cur.execute(
            f"CREATE DATABASE [{db_name}] ON PRIMARY "
            f"(NAME = N'{db_name}', FILENAME = N'{_sql_path(mdf)}') "
            f"LOG ON (NAME = N'{db_name}_log', FILENAME = N'{_sql_path(ldf)}')"
        )
    except pyodbc.Error:
        # 项目目录不可写（例如放在 Program Files）时退回实例默认目录
        cur.execute(f"CREATE DATABASE [{db_name}]")


def execute_script(conn: pyodbc.Connection, script: str) -> None:
    """按 GO 分批执行脚本（SQL Server 同一批次内不能引用刚新增的列）。"""
    batch: list[str] = []
    for raw in script.splitlines():
        if raw.strip().upper() == "GO":
            chunk = "\n".join(batch).strip()
            if chunk:
                conn.execute(chunk)
            batch = []
        else:
            batch.append(raw)
    chunk = "\n".join(batch).strip()
    if chunk:
        conn.execute(chunk)


def row_to_dict(cursor: pyodbc.Cursor, row: Iterable[Any]) -> dict[str, Any]:
    columns = [item[0] for item in cursor.description]
    data = dict(zip(columns, row))
    for key, value in list(data.items()):
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat(sep=" ", timespec="seconds")
    return data


def query_all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    ensure_database()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        rows = [row_to_dict(cur, row) for row in cur.fetchall()]
        return rows
    finally:
        conn.close()


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = (), *, fetch_identity: bool = False) -> int:
    """执行写操作；fetch_identity=True 时返回新插入行的 id。"""
    ensure_database()
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        new_id = 0
        if fetch_identity:
            row = cur.fetchone()
            new_id = int(row[0]) if row else 0
        conn.commit()
        return new_id if fetch_identity else cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction():
    ensure_database()
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def health() -> dict[str, Any]:
    ensure_database()
    conn = connect()
    try:
        cur = conn.cursor()
        version = cur.execute("SELECT @@VERSION").fetchone()[0].splitlines()[0]
        db_name = cur.execute("SELECT DB_NAME()").fetchone()[0]
        return {"ok": True, "database": db_name, "server": version}
    finally:
        conn.close()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
