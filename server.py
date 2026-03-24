from fastapi import FastAPI
from pydantic import BaseModel
import ollama
import json
import logging
from datetime import datetime

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S.RAM!")

# 오류 데이터 입력 형식
class ErrorData(BaseModel):
    data: dict

# 프롬프트 생성
def build_prompt(data: dict) -> str:
    return f"""
You are a security AI for a robotic monitoring system (S.RAM!).
Analyze the following error data and respond ONLY in JSON format.

Error Data:
{json.dumps(data, indent=2)}

Respond ONLY with this JSON structure, no extra text:
{{
  "threat": true or false,
  "level": "LOW" or "MEDIUM" or "HIGH" or "CRITICAL",
  "cause": "brief cause explanation",
  "action": "recommended action"
}}
"""

# 레벨별 처리
def handle_threat_level(level: str, result: dict):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if level == "LOW":
        logger.info(f"[{timestamp}] ✅ LOW - {result['cause']}")

    elif level == "MEDIUM":
        logger.warning(f"[{timestamp}] ⚠️  MEDIUM - {result['cause']}")
        logger.warning(f"  → 조치: {result['action']}")

    elif level == "HIGH":
        logger.error(f"[{timestamp}] 🔴 HIGH - {result['cause']}")
        logger.error(f"  → 조치: {result['action']}")
        # TODO: Tier3 관제 대시보드에 알림 전송
        notify_dashboard(result)

    elif level == "CRITICAL":
        logger.critical(f"[{timestamp}] 🚨 CRITICAL - {result['cause']}")
        logger.critical(f"  → 즉시 조치: {result['action']}")
        # TODO: 로봇 정지 명령
        notify_dashboard(result)
        emergency_stop()

def notify_dashboard(result: dict):
    # 나중에 Tier3 Ubuntu로 HTTP POST 날릴 곳
    logger.info("대시보드에 알림 전송 (미구현)")

def emergency_stop():
    # 나중에 ESP32로 정지 명령 날릴 곳
    logger.critical("로봇 긴급 정지 명령 전송 (미구현)")

@app.post("/analyze")
async def analyze(error: ErrorData):
    prompt = build_prompt(error.data)
    
    response = ollama.chat(
        model="llama3.1:8b",
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = response["message"]["content"]
    
    # JSON 파싱
    try:
        result = json.loads(raw)
        level = result.get("level", "UNKNOWN")
        handle_threat_level(level, result)
    except json.JSONDecodeError:
        result = {"raw": raw, "parse_error": "LLM did not return valid JSON"}
    
    return result