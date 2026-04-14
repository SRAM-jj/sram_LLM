from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re
import ollama
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
import httpx
import asyncio
from database import init_db, save_to_db
from mqtt_client import emergency_stop

# ── 환경변수 설정 ─────────────────────────────────────────────
DASHBOARD_URL  = os.getenv("DASHBOARD_URL", "http://localhost:8001")
LLM_MODEL      = os.getenv("LLM_MODEL", "llama3.1:8b")
API_KEY        = os.getenv("API_KEY", "")
RATE_LIMIT     = int(os.getenv("RATE_LIMIT", "60"))       # 분당 최대 요청 수
RATE_WINDOW    = int(os.getenv("RATE_WINDOW", "60"))       # 윈도우 크기 (초)

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S.RAM!")

# ── 인증 ─────────────────────────────────────────────────────
def verify_api_key(request: Request):
    if not API_KEY:
        return  # API_KEY 미설정 시 인증 비활성화 (개발 환경)
    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# ── Rate Limiting ────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)

def rate_limit(request: Request):
    client_ip = request.client.host
    now = time.time()
    window_start = now - RATE_WINDOW
    # 윈도우 내 요청만 유지
    _rate_store[client_ip] = [t for t in _rate_store[client_ip] if t > window_start]
    if len(_rate_store[client_ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_store[client_ip].append(now)

@app.on_event("startup")
async def startup():
    init_db()

# ── 프롬프트 ──────────────────────────────────────────────────
# 절대기준 JSON 포맷 (sram_router 기준):
# {
#   "device_id": "ARM_NODE_01",
#   "timestamp": 123456789,
#   "status": {"state": "ERROR", "error_code": 4021, "emergency_stop": true},
#   "joints": {
#     "names": ["base", "shoulder", "elbow", "wrist", "gripper"],
#     "positions": [1.57, -0.52, 1.20, 0.0, 0.5],
#     "efforts": [12.5, 210.5, 30.1, 5.0, 1.2],
#     "temperatures": [35.2, 88.3, 38.0, 32.1, 30.0]
#   },
#   "end_effector": {
#     "pose": {"x": 250.5, "y": 100.2, "z": 300.0, "roll": 0.0, "pitch": 1.57, "yaw": 0.0},
#     "gripper_active": true
#   }
# }

VALID_STATES = {"SAFE", "WARNING", "DANGER", "ERROR"}
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

class StatusData(BaseModel):
    state: str = "unknown"
    error_code: Optional[int] = None
    emergency_stop: Optional[bool] = None

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        upper = v.upper()
        if upper not in VALID_STATES:
            return "unknown"
        return upper

class JointsData(BaseModel):
    names: Optional[list[str]] = None
    positions: Optional[list[float]] = None
    efforts: list[float] = Field(default_factory=list, max_length=20)
    temperatures: list[float] = Field(default_factory=list, max_length=20)

    @field_validator("efforts", "temperatures")
    @classmethod
    def validate_ranges(cls, v: list[float]) -> list[float]:
        for val in v:
            if not (-1000 <= val <= 1000):
                raise ValueError(f"Value {val} out of valid range [-1000, 1000]")
        return v

class SensorData(BaseModel):
    device_id: str = "unknown"
    timestamp: Optional[int] = None
    status: StatusData = StatusData()
    joints: JointsData = JointsData()

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not DEVICE_ID_PATTERN.match(v):
            return "unknown"
        return v

class ErrorData(BaseModel):
    data: SensorData

def build_prompt(data: SensorData) -> str:
    # 프롬프트 인젝션 방지: 수치 데이터만 전달
    safe_input = {
        "device_id": data.device_id,
        "state": data.status.state,
        "efforts": data.joints.efforts,
        "temperatures": data.joints.temperatures,
    }
    if data.joints.names:
        safe_input["joint_names"] = data.joints.names

    return f"""
You are a security AI for a robotic monitoring system (S.RAM!).
Analyze the following robot arm joint data and respond ONLY in JSON format.

IMPORTANT: The ONLY valid level values are "WARNING", "DANGER", and "ERROR".

Input fields:
- efforts: torque values per joint [Nm]
- temperatures: temperature per joint [°C]
- state: pre-classified state from router (SAFE/WARNING/DANGER/ERROR)

Threat level rules (ABSOLUTE - must follow exactly):
- max effort > 50 Nm  OR  max temperature > 45°C  → level = "ERROR"
- max effort > 30 Nm  OR  max temperature > 40°C  → level = "DANGER"
- otherwise                                        → level = "WARNING"

Examples:
Input: {{"device_id": "ARM_NODE_01", "state": "WARNING", "efforts": [12.5, 25.0, 10.0, 5.0, 1.2], "temperatures": [35.0, 38.0, 34.0, 32.0, 30.0]}}
Output: {{"threat": true, "level": "WARNING", "cause": "Moderate joint torque detected. shoulder joint showing elevated effort.", "action": "Monitor continuously and log for trend analysis."}}

Input: {{"device_id": "ARM_NODE_01", "state": "DANGER", "efforts": [35.0, 40.0, 20.0, 8.0, 2.0], "temperatures": [39.0, 43.0, 37.0, 33.0, 31.0]}}
Output: {{"threat": true, "level": "DANGER", "cause": "High joint torque and temperature approaching critical limits on shoulder joint.", "action": "Reduce speed and payload. Monitor temperature continuously."}}

Input: {{"device_id": "ARM_NODE_01", "state": "ERROR", "efforts": [12.5, 210.5, 30.1, 5.0, 1.2], "temperatures": [35.2, 88.3, 38.0, 32.1, 30.0]}}
Output: {{"threat": true, "level": "ERROR", "cause": "Critical torque (210.5 Nm) and temperature (88.3°C) on shoulder joint far exceed safe limits.", "action": "EMERGENCY STOP. Cool down joints and inspect mechanical components immediately."}}

Now analyze this:
Input: {json.dumps(safe_input)}
Output:
"""

# ── 위협 레벨 처리 ────────────────────────────────────────────
def handle_threat_level(level: str, result: dict):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if level == "WARNING":
        logger.warning(f"[{timestamp}] ⚠️  WARNING - {result['cause']}")
        logger.warning(f"  → 조치: {result['action']}")
        notify_dashboard(result)
    elif level == "DANGER":
        logger.error(f"[{timestamp}] 🔴 DANGER - {result['cause']}")
        logger.error(f"  → 조치: {result['action']}")
        notify_dashboard(result)
    elif level == "ERROR":
        logger.critical(f"[{timestamp}] 🚨 ERROR - {result['cause']}")
        logger.critical(f"  → 즉시 조치: {result['action']}")
        notify_dashboard(result)
        emergency_stop()

def notify_dashboard(result: dict):
    logger.info("📡 대시보드에 알림 전송")
    try:
        httpx.post(f"{DASHBOARD_URL}/notify", json=result, timeout=2)
    except:
        pass

# ── API ───────────────────────────────────────────────────────
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "10"))  # 초 단위, 기본 10초

def rule_based_level(joints: dict) -> str:
    efforts = joints.get("efforts", [])
    temperatures = joints.get("temperatures", [])
    max_effort = max(efforts) if efforts else 0
    max_temp = max(temperatures) if temperatures else 0

    if max_temp > 45 or max_effort > 50:
        return "ERROR"
    elif max_temp > 40 or max_effort > 30:
        return "DANGER"
    else:
        return "WARNING"

@app.post("/analyze", dependencies=[Depends(verify_api_key), Depends(rate_limit)])
async def analyze(error: ErrorData):
    sensor = error.data
    input_dict = sensor.model_dump()
    prompt = build_prompt(sensor)
    joints = {"efforts": sensor.joints.efforts, "temperatures": sensor.joints.temperatures}
    loop = asyncio.get_event_loop()

    def parse_llm_response(raw: str) -> dict | None:
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        if "}" in clean:
            clean = clean[:clean.rfind("}")+1]
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return None

    # LLM 호출 + JSON 파싱 (최대 1회 재시도, 타임아웃 적용)
    raw = None
    result = None
    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: ollama.chat(
                        model=LLM_MODEL,
                        messages=[{"role": "user", "content": prompt}]
                    )
                ),
                timeout=LLM_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  LLM 응답 {LLM_TIMEOUT}초 초과 (시도 {attempt + 1}){' — 재시도 중...' if attempt == 0 else ' — 규칙 기반 fallback 적용'}")
            continue

        raw = response["message"]["content"]
        result = parse_llm_response(raw)
        if result is not None:
            break
        logger.warning(f"⚠️  LLM JSON 파싱 실패 (시도 {attempt + 1}){' — 재시도 중...' if attempt == 0 else ''}")

    if result is not None:
        result["input"] = input_dict
        # 규칙 기반 레벨 보정 (joints 데이터 기준)
        result["level"] = rule_based_level(joints)
        level = result["level"]
        handle_threat_level(level, result)
        save_to_db(level, result, input_dict)
        return result

    # 최종 fallback — 규칙 기반 단독 판단
    logger.error("🔁 LLM 실패 — 규칙 기반 fallback 적용")
    level = rule_based_level(joints)
    fallback = {
        "threat": level != "SAFE",
        "level": level,
        "cause": "LLM unavailable — rule-based fallback applied.",
        "action": "Check LLM service and output format.",
        "input": input_dict
    }
    if raw:
        fallback["raw"] = raw
        fallback["parse_error"] = "LLM did not return valid JSON after 1 retry."
    handle_threat_level(level, fallback)
    save_to_db(level, fallback, input_dict)
    return fallback

@app.post("/emergency_stop", dependencies=[Depends(verify_api_key), Depends(rate_limit)])
async def emergency_stop_endpoint():
    emergency_stop()
    return {"ok": True}
