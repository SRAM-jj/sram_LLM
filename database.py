import os
import logging
import psycopg2
from psycopg2.extras import Json

logger = logging.getLogger("S.RAM!")

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "sram")
DB_USER     = os.getenv("DB_USER", "sram_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def get_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS threat_logs (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP DEFAULT NOW(),
                device_id   VARCHAR(100),
                level       VARCHAR(10) NOT NULL,
                state       VARCHAR(20),
                max_effort  FLOAT,
                max_temp    FLOAT,
                input_data  JSONB,
                cause       TEXT,
                action      TEXT
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ DB 초기화 완료")
    except Exception as e:
        logger.warning(f"⚠️ DB 연결 실패 (Ubuntu 배포 시 설정 필요): {e}")


def save_to_db(level: str, result: dict, input_data: dict):
    try:
        joints = input_data.get("joints", {})
        efforts = joints.get("efforts", [])
        temperatures = joints.get("temperatures", [])

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO threat_logs (device_id, level, state, max_effort, max_temp, input_data, cause, action)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            input_data.get("device_id"),
            level,
            input_data.get("status", {}).get("state"),
            max(efforts) if efforts else None,
            max(temperatures) if temperatures else None,
            Json(input_data),
            result.get("cause"),
            result.get("action")
        ))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("💾 DB 저장 완료")
    except Exception as e:
        logger.warning(f"⚠️ DB 저장 실패: {e}")
