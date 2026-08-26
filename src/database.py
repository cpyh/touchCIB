"""Shared MySQL connection for the Flask service."""

from __future__ import annotations

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def database_connection(*, autocommit: bool = False):
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "cib"),
        charset="utf8mb4",
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        cursorclass=DictCursor,
        autocommit=autocommit,
    )
