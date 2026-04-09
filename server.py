from fastapi import FastAPI
from pydantic import BaseModel
import ollama
import json
import logging
import os
from datetime import datetime
import httpx
import asyncio
from database import init_db, save_to_db
from mqtt_client import emergency_stop

# ── 환경변수 설정 ─────────────────────────────────────────────
DASHBOARD_URL  = os.getenv("DASHBOARD_URL", "http://localhost:8001")
LLM_MODEL      = os.getenv("LLM_MODEL", "llama3.1:8b")

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S.RAM!")

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

class ErrorData(BaseModel):
    data: dict

def build_prompt(data: dict) -> str:
    return f"""
You are a security AI for a robotic monitoring system (S.RAM!).
Analyze the following robot arm joint data and respond ONLY in JSON format.

IMPORTANT: The ONLY valid level values are "WARNING", "DANGER", and "ERROR".

Input fields:
- joints.efforts: torque values per joint [Nm]
- joints.temperatures: temperature per joint [°C]
- status.state: pre-classified state from router (Safe/Warning/Danger/Error)

Threat level rules (ABSOLUTE - must follow exactly):
- max effort > 50 Nm  OR  max temperature > 45°C  → level = "ERROR"
- max effort > 30 Nm  OR  max temperature > 40°C  → level = "DANGER"
- otherwise                                        → level = "WARNING"

Examples:
Input: {{"device_id": "ARM_NODE_01", "status": {{"state": "WARNING"}}, "joints": {{"names": ["base", "shoulder", "elbow", "wrist", "gripper"], "efforts": [12.5, 25.0, 10.0, 5.0, 1.2], "temperatures": [35.0, 38.0, 34.0, 32.0, 30.0]}}}}
Output: {{"threat": true, "level": "WARNING", "cause": "Moderate joint torque detected. shoulder joint showing elevated effort.", "action": "Monitor continuously and log for trend analysis."}}

Input: {{"device_id": "ARM_NODE_01", "status": {{"state": "DANGER"}}, "joints": {{"names": ["base", "shoulder", "elbow", "wrist", "gripper"], "efforts": [35.0, 40.0, 20.0, 8.0, 2.0], "temperatures": [39.0, 43.0, 37.0, 33.0, 31.0]}}}}
Output: {{"threat": true, "level": "DANGER", "cause": "High joint torque and temperature approaching critical limits on shoulder joint.", "action": "Reduce speed and payload. Monitor temperature continuously."}}

Input: {{"device_id": "ARM_NODE_01", "status": {{"state": "ERROR"}}, "joints": {{"names": ["base", "shoulder", "elbow", "wrist", "gripper"], "efforts": [12.5, 210.5, 30.1, 5.0, 1.2], "temperatures": [35.2, 88.3, 38.0, 32.1, 30.0]}}}}
Output: {{"threat": true, "level": "ERROR", "cause": "Critical torque (210.5 Nm) and temperature (88.3°C) on shoulder joint far exceed safe limits.", "action": "EMERGENCY STOP. Cool down joints and inspect mechanical components immediately."}}

Now analyze this:
Input: {json.dumps(data)}
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

@app.post("/analyze")
async def analyze(error: ErrorData):
    prompt = build_prompt(error.data)
    joints = error.data.get("joints", {})
    loop = asyncio.get_event_loop()

    def parse_llm_response(raw: str) -> dict | None:
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        if "}" in clean:
            clean = clean[:clean.rfind("}")+1]
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return None

    # LLM 호출 + JSON 파싱 (최대 1회 재시도)
    raw = None
    result = None
    for attempt in range(2):
        response = await loop.run_in_executor(
            None,
            lambda: ollama.chat(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
        )
        raw = response["message"]["content"]
        result = parse_llm_response(raw)
        if result is not None:
            break
        logger.warning(f"⚠️  LLM JSON 파싱 실패 (시도 {attempt + 1}){' — 재시도 중...' if attempt == 0 else ''}")

    if result is not None:
        result["input"] = error.data
        # 규칙 기반 레벨 보정 (joints 데이터 기준)
        result["level"] = rule_based_level(joints)
        level = result["level"]
        handle_threat_level(level, result)
        save_to_db(level, result, error.data)
        return result

    # 최종 fallback — 규칙 기반 단독 판단
    logger.error("🔁 LLM JSON 파싱 2회 실패 — 규칙 기반 fallback 적용")
    level = rule_based_level(joints)
    fallback = {
        "threat": level != "SAFE",
        "level": level,
        "cause": "LLM parse error — rule-based fallback applied.",
        "action": "Check LLM output format.",
        "raw": raw,
        "parse_error": "LLM did not return valid JSON after 1 retry.",
        "input": error.data
    }
    handle_threat_level(level, fallback)
    save_to_db(level, fallback, error.data)
    return fallback

@app.post("/emergency_stop")
async def emergency_stop_endpoint():
    emergency_stop()
    return {"ok": True}
