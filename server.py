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
class ErrorData(BaseModel):
    data: dict

def build_prompt(data: dict) -> str:
    return f"""
You are a security AI for a robotic monitoring system (S.RAM!).
Analyze the following error data and respond ONLY in JSON format.

IMPORTANT: The ONLY valid level values are "WARNING", "DANGER", and "ERROR". Never use "CRITICAL" or any other value.

Threat level rules (ABSOLUTE - must follow exactly):
- force_x_max < 100  → level = "WARNING"
- force_x_max 100~179 → level = "DANGER"
- force_x_max >= 180  → level = "ERROR"

Examples:
Input: {{"error_type": "collision", "failure_type": "Transfer Failure", "force_x_max": 60, "torque_x_min": -50}}
Output: {{"threat": true, "level": "WARNING", "cause": "Moderate collision during transfer, force exceeds normal range.", "action": "Pause operation and inspect gripper mechanism."}}

Input: {{"error_type": "collision", "failure_type": "Approach to Grip Failure", "force_x_max": 140, "torque_x_min": -130}}
Output: {{"threat": true, "level": "DANGER", "cause": "Severe collision detected, dangerously high force and torque.", "action": "Immediate shutdown and full mechanical inspection required."}}

Input: {{"error_type": "obstruction", "failure_type": "Move Failure", "force_x_max": 250, "torque_x_min": -220}}
Output: {{"threat": true, "level": "ERROR", "cause": "Critical obstruction with extreme force, risk of permanent damage.", "action": "EMERGENCY STOP. Disconnect power and perform full system diagnostic."}}

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
@app.post("/analyze")
async def analyze(error: ErrorData):
    prompt = build_prompt(error.data)

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
    )

    raw = response["message"]["content"]

    try:
        clean = raw.strip()
        clean = clean.replace("```json", "").replace("```", "").strip()
        if "}" in clean:
            clean = clean[:clean.rfind("}")+1]
        result = json.loads(clean)

        result["input"] = error.data

        # 규칙 기반 레벨 보정
        force_x_max = error.data.get("force_x_max")
        if force_x_max is not None:
            if force_x_max < 100:
                result["level"] = "WARNING"
            elif force_x_max < 180:
                result["level"] = "DANGER"
            else:
                result["level"] = "ERROR"

        level = result.get("level", "UNKNOWN")
        handle_threat_level(level, result)
        save_to_db(level, result, error.data)

    except json.JSONDecodeError:
        result = {"raw": raw, "parse_error": "LLM did not return valid JSON"}

    return result

@app.post("/emergency_stop")
async def emergency_stop_endpoint():
    emergency_stop()
    return {"ok": True}
