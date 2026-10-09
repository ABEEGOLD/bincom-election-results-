import os

import pymysql
from dotenv import load_dotenv

load_dotenv()  # reads the .env file in the project folder


def get_connection():
    """Open a new connection to MySQL using the settings from .env."""
    options = {}
    if os.environ.get("DB_SSL", "").lower() in ("1", "true", "yes"):
        # Cloud MySQL services (for example Aiven) only accept encrypted connections.
        options["ssl"] = {"check_hostname": False}
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,  # rows come back as dictionaries
        **options,
    )


def fetch_all(sql, params=()):
    """Run a SELECT and return every row."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def fetch_one(sql, params=()):
    """Run a SELECT and return the first row (or None)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()
