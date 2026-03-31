# S.RAM! — LLM 파트

로봇 암이 충돌, 장애물 감지, 이상 동작 등의 오류를 감지하면,
센서 데이터를 이 서버로 전송.
서버는 **LLM** 을 사용해 위협 수준을 분석,
필요 시 로봇에 **긴급 정지 명령**을 내림.

---

## 전체 시스템 구조

```
[ESP32] ──MQTT──▶ [Raspberry Pi] ──MQTT──▶ [Ubuntu PC (Tier3)]
                                                    │
                                               HTTP POST
                                                    │
                                                    ▼
                                        [이 서버 - FastAPI + Ollama]
                                         llama3.1:8b 모델로 분석
                                                    │
                                      ┌─────────────┼─────────────┐
                                      ▼             ▼             ▼
                              분석 결과 반환    DB 저장       MQTT 긴급정지
                           (JSON: 위협레벨,  (threat_logs)   (ERROR 시)
                            원인, 조치)
```

**이 서버의 역할 = Tier4 (최종 AI 분석 계층)**

---

## 위협 레벨 기준 (현재 수치는 임시값)

| 레벨 | force_x_max 기준 | 동작 |
|------|-----------------|------|
| **WARNING** | < 100 | 로그 + 대시보드 알림 |
| **DANGER** | 100 ~ 179 | 로그 + 대시보드 알림 |
| **ERROR** | ≥ 180 | 로그 + 대시보드 알림 + MQTT 긴급정지 + DB 저장 |

---

## 프로젝트 구조

```
sram_llm/
├── server.py                  # FastAPI 메인 서버 (AI 분석 + API 엔드포인트)
├── database.py                # PostgreSQL 연결, 테이블 생성, 로그 저장
├── mqtt_client.py             # MQTT 긴급정지 명령 전송 (Raspberry Pi)
├── .env.example               # 환경변수 설정 예시 (배포할때 IP 채우기)
├── prepare_training_data.py   # 데이터셋 → 학습용 JSONL 변환 스크립트
├── finetune.sh                # MLX 파인튜닝 실행 스크립트 (Mac M-series용)
├── Modelfile                  # Ollama 커스텀 모델 등록 파일
├── datasheet/                 # 학습에 사용된 데이터셋 원본
│   ├── lp1~lp5.data.txt       # UCI Robot Execution Failures (463 샘플)
│   ├── ai4i2020.csv           # AI4I Predictive Maintenance (10,000행)
│   └── ur5testresult_*.csv    # NIST UR5 로봇 암 데이터 (134,933행)
├── training_data/             # 변환된 학습 데이터 (JSONL)
│   ├── train.jsonl            # 훈련 데이터 6,653개
│   └── valid.jsonl            # 검증 데이터 740개
└── adapters/                  # LoRA 파인튜닝 결과물
```

---

## LLM 작동 방식

### 분석 흐름

```
센서 데이터 수신 (force_x_max, torque_x_min, error_type 등)
        │
        ▼
  프롬프트 생성 (Few-shot 예시 포함)
        │
        ▼
  Ollama LLM 분석 (llama3.1:8b)
        │
        ▼
  JSON 파싱 (threat, level, cause, action)
        │
        ▼
  규칙 기반 레벨 보정 ← force_x_max 기준으로 레벨 강제 덮어쓰기
        │
        ▼
  결과 반환 + DB 저장 + 필요 시 긴급정지
```

### 규칙 기반 보정이 필요한 이유

LLM은 확률 기반이라 같은 입력이라도 레벨을 다르게 판단할 수 있음.
`force_x_max` 수치는 명확한 기준이 있으므로, LLM 응답과 관계없이
코드에서 강제로 레벨을 덮어씌워 일관성을 보장함.

```python
# server.py — 규칙 기반 레벨 보정
if force_x_max < 100:
    result["level"] = "WARNING"
elif force_x_max < 180:
    result["level"] = "DANGER"
else:
    result["level"] = "ERROR"
```

### 프롬프트 구조

Few-shot 방식 — 예시 3개(WARNING/DANGER/ERROR)를 프롬프트에 포함해
LLM이 원인(cause)과 조치(action)를 올바른 형식으로 반환하도록 유도.
레벨 자체는 규칙 기반으로 보정되므로, LLM은 원인/조치 문장 생성에 집중.

---

## 로컬 실행 (개발 환경 MAC)

처음 세팅하는 경우 1~3을 순서대로 진행.
이미 세팅된 경우 4번(서버 실행)만 하면 됨.

### 1. 사전 준비 (최초 1회)

```bash
# Ollama 설치
brew install ollama

# 모델 다운로드
ollama pull llama3.1:8b

# MQTT 브로커 설치
brew install mosquitto
mkdir -p /opt/homebrew/etc/mosquitto
echo "listener 1883\nallow_anonymous true" > /opt/homebrew/etc/mosquitto/mosquitto.conf
```

### 2. Python 환경 설정 (최초 1회)

```bash
cd ~/Desktop/sram_llm
python3 -m venv venv_new
source venv_new/bin/activate
pip install fastapi uvicorn httpx ollama paho-mqtt websockets 'uvicorn[standard]' psycopg2-binary
```

### 3. 환경변수 설정 (최초 1회)

```bash
cp .env.example .env
# .env 파일을 열어 IP 주소 등 값을 수정
```

### 4. 서버 실행 (터미널 3개)

**터미널 1 — Ollama**
```bash
ollama serve
```

**터미널 2 — LLM 서버**
```bash
cd ~/Desktop/sram_llm
source venv_new/bin/activate
uvicorn server:app --reload --reload-exclude 'venv*'
```

**터미널 3 — MQTT 브로커**
```bash
/opt/homebrew/opt/mosquitto/sbin/mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf
```

### 5. 작동 확인

서버가 정상적으로 떴는지 아래 명령어로 테스트:

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"data": {"error_type": "collision", "force_x_max": 150}}'
```

**정상 응답 예시:**
```json
{
  "threat": true,
  "level": "DANGER",
  "cause": "Severe collision detected, dangerously high force.",
  "action": "Immediate shutdown and full mechanical inspection required.",
  "input": {"error_type": "collision", "force_x_max": 150}
}
```

> Mac에서는 PostgreSQL 없어도 서버 정상 작동 (DB 연결 실패 시 경고 로그만 출력)

---

## 추후 우분투 배포 (Ubuntu RTX 4070 - Tier4 서버)

### 1. 사전 준비

```bash
# Ollama 설치
curl -fsSL https://ollama.com/install.sh | sh

# 모델 다운로드
ollama pull llama3.1:8b

# MQTT 브로커
sudo apt install mosquitto -y
echo "listener 1883\nallow_anonymous true" | sudo tee /etc/mosquitto/conf.d/sram.conf
sudo systemctl enable --now mosquitto
```

### 2. PostgreSQL 설치 및 설정

```bash
sudo apt install postgresql postgresql-contrib -y
sudo systemctl enable --now postgresql

# DB 및 유저 생성
sudo -u postgres psql <<EOF
CREATE USER sram_user WITH PASSWORD '비밀번호설정';
CREATE DATABASE sram OWNER sram_user;
EOF
```

> 테이블은 서버 최초 실행 시 자동 생성됨 (따로 스키마 실행 불필요)

### 3. 코드 설치

```bash
git clone [GitHub 주소]
cd sram_llm
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn httpx ollama paho-mqtt websockets 'uvicorn[standard]' psycopg2-binary
```

### 4. 환경변수 설정

```bash
cp .env.example .env
nano .env
```

**env 파일 예시**

```env
MQTT_BROKER=192.168.x.x               # Raspberry Pi IP
DASHBOARD_URL=http://192.168.x.x:8001  # Tier3 Ubuntu IP
LLM_MODEL=llama3.1:8b

DB_HOST=localhost
DB_PORT=5432
DB_NAME=sram
DB_USER=sram_user
DB_PASSWORD=비밀번호설정
```

### 5. 서버 실행

```bash
# 터미널 1
ollama serve

# 터미널 2
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000
```

> `--host 0.0.0.0` 필수 — Tier3에서 이 서버로 접근하려면 모든 IP 허용해야 함

---

## API 사용법

### POST /analyze — 센서 데이터 분석

**요청:**
```bash
curl -X POST http://[서버IP]:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"data": {"error_type": "collision", "force_x_max": 185}}'
```

**응답:**
```json
{
  "threat": true,
  "level": "ERROR",
  "cause": "Severe collision detected with extreme force.",
  "action": "EMERGENCY STOP. Disconnect power and perform full system diagnostic.",
  "input": {"error_type": "collision", "force_x_max": 185}
}
```

### POST /emergency_stop — 수동 긴급정지

```bash
curl -X POST http://[서버IP]:8000/emergency_stop
```

---

## Tier3에서 이 서버로 데이터 보내는 방법

```python
import httpx

response = httpx.post(
    "http://[Tier4_IP]:8000/analyze",
    json={"data": 오류데이터_딕셔너리}
)
result = response.json()
print(result["level"])   # "WARNING" / "DANGER" / "ERROR"
print(result["cause"])   # 원인 설명 출력
print(result["action"])  # 권장 조치 출력
```

---

## 데이터베이스 (PostgreSQL)

### 구현 완료
- 서버 시작 시 `threat_logs` 테이블 자동 생성
- `/analyze` 호출마다 위협 분석 결과 자동 저장
- DB 연결 실패 시 서버는 정상 작동 (Mac 개발 환경에서 DB 없어도 됨)

**저장되는 데이터 (threat_logs 테이블):**
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL | 자동 증가 PK |
| timestamp | TIMESTAMP | 분석 시각 |
| level | VARCHAR | WARNING / DANGER / ERROR |
| error_type | VARCHAR | 오류 유형 (collision 등) |
| force_x_max | FLOAT | 최대 충격력 |
| input_data | JSONB | 센서 원본 데이터 전체 |
| cause | TEXT | LLM이 판단한 원인 |
| action | TEXT | LLM이 제안한 조치 |

**파일 역할 분리:**
```
server.py      # API 엔드포인트 + LLM 분석 흐름
database.py    # DB 연결, 테이블 생성, 저장
mqtt_client.py # MQTT 긴급정지 전송
```

### 미구현 (추후 작업)
- 저장된 로그 조회 API (`GET /logs`) — 팀 논의 후 추가 예정

---

## LLM 파인튜닝 (우분투에서 추후 작업)

현재는 `llama3.1:8b` 기반으로 동작.
RTX 4070 Ubuntu 서버에서 실제 데이터로 파인튜닝할 계획.

**학습 데이터:**
- `training_data/train.jsonl` — 6,653개 샘플
- `training_data/valid.jsonl` — 740개 샘플
- 데이터 출처: UCI Robot Failures + AI4I 2020 + NIST UR5

**파인튜닝 방법 (Mac M-series):**
```bash
bash finetune.sh
```

**파인튜닝 완료 후 모델 교체:**
```env
# .env
LLM_MODEL=sram-ai   # 파인튜닝된 커스텀 모델
```

---

## 개발 환경

| 항목 | 내용 |
|------|------|
| 개발 | MacBook Air M4 16GB |
| 배포 | Ubuntu PC RTX 4070 (Tier4) |
| 모델 | Ollama llama3.1:8b |
| 프레임워크 | FastAPI + Uvicorn |
| 통신 | HTTP (Tier3 → Tier4), MQTT (긴급정지) |
| DB | PostgreSQL (위협 로그 저장) |
