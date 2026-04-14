from collections.abc import Iterator
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings


pool = ConnectionPool(
    conninfo=get_settings().database_url,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
)


@contextmanager
def get_conn() -> Iterator:
    with pool.connection() as conn:
        yield conn


def close_pool() -> None:
    pool.close()
