from __future__ import annotations

from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from .config import settings


def get_connection(*, database: bool = True, autocommit: bool = False):
    options = {
        "host": settings.db_host,
        "port": settings.db_port,
        "user": settings.db_user,
        "password": settings.db_password,
        "charset": "utf8mb4",
        "connect_timeout": settings.db_connect_timeout,
        "cursorclass": DictCursor,
        "autocommit": autocommit,
    }
    if database:
        options["database"] = settings.db_name
    return pymysql.connect(**options)


@contextmanager
def transaction():
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
