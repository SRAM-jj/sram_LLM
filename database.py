import os
import json
import logging
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

logger = logging.getLogger("S.RAM!")

INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "sram")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "threat_logs")


def get_client():
    return InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)


def init_db():
    """InfluxDB 연결 확인 (버킷은 InfluxDB UI 또는 CLI에서 미리 생성 필요)"""
    try:
        with get_client() as client:
            health = client.health()
            if health.status == "pass":
                logger.info("✅ InfluxDB 연결 완료")
            else:
                logger.warning(f"⚠️ InfluxDB 상태 이상: {health.status}")
    except Exception as e:
        logger.warning(f"⚠️ InfluxDB 연결 실패 (Ubuntu 배포 시 설정 필요): {e}")


def save_to_db(level: str, result: dict, input_data: dict):
    """위협 분석 결과를 InfluxDB에 저장"""
    try:
        joints       = input_data.get("joints", {})
        efforts      = joints.get("efforts", [])
        temperatures = joints.get("temperatures", [])

        point = (
            Point("threat_logs")
            # Tags (인덱싱 — 필터링/그룹화에 사용)
            .tag("device_id", input_data.get("device_id", "unknown"))
            .tag("level",     level)
            .tag("state",     input_data.get("status", {}).get("state", "unknown"))
            # Fields (실제 측정값)
            .field("max_effort", max(efforts)      if efforts      else 0.0)
            .field("max_temp",   max(temperatures) if temperatures else 0.0)
            .field("cause",      result.get("cause",  ""))
            .field("action",     result.get("action", ""))
            .field("input_data", json.dumps(input_data))
            .time(datetime.now(timezone.utc))
        )

        with get_client() as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            write_api.write(bucket=INFLUX_BUCKET, record=point)

        logger.info("💾 InfluxDB 저장 완료")

    except Exception as e:
        logger.warning(f"⚠️ InfluxDB 저장 실패: {e}")
