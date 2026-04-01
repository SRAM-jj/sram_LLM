# S.RAM! — LLM 파트

로봇 암이 충돌, 장애물 감지, 이상 동작 등의 오류를 감지하면,
센서 데이터를 이 서버로 전송.
서버는 **LLM** 을 사용해 위협 수준을 분석,
필요 시 로봇에 **긴급 정지 명령**을 내림.

---

## 전체 시스템 구조

```
[ESP32] ──MQTT──▶ [Raspberry Pi (Tier2)]
                          │
                     HTTP POST
                          │
                          ▼
              [이 서버 - FastAPI + Ollama (Tier4)]
               llama3.1:8b 모델로 위협 분석
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   HTTP POST 결과 전달  DB 저장       MQTT 긴급정지
   [Ubuntu PC (Tier3)] (threat_logs)   (ERROR 시)
    백엔드/대시보드
```

**이 서버의 역할 = Tier4 (라우터-백엔드 사이 AI 분석 계층)**
- Raspberry Pi로부터 센서 데이터를 받아 LLM으로 분석
- 분석 결과를 Tier3 Ubuntu PC(백엔드)로 전달

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
├── finetune_ubuntu.py         # QLoRA 파인튜닝 스크립트 (Ubuntu RTX 4070용)
├── merge_adapter.py           # LoRA 어댑터 → 베이스 모델 병합
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

### 규칙 기반 보정 필요한 이유

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

## 우분투 배포 (Ubuntu RTX 4070 - Tier4 서버)

`server.py`, `database.py`, `mqtt_client.py` 는 우분투에서 그대로 동작함.
현재 `llama3.1:8b` 기반으로 바로 운용 가능하며, 파인튜닝은 선택사항임.

| | 지금 (llama3.1:8b) | 파인튜닝 후 (sram-ai) |
|---|---|---|
| 서버 코드 | 동일 | 동일 |
| 분석 정확도 | 괜찮음 | 더 좋음 |
| 모델 설정 | `LLM_MODEL=llama3.1:8b` | `LLM_MODEL=sram-ai` |

처음 세팅하는 경우 1~5를 순서대로 진행.
이미 세팅된 경우 6번(서버 실행)만 하면 됨.

### 1. 코드 받기 (최초 1회)

```bash
git clone https://github.com/SRAM-jj/sram_LLM.git
cd sram_LLM
```

### 2. Ollama 설치 및 모델 다운로드 (최초 1회)

```bash
# Ollama 설치
curl -fsSL https://ollama.com/install.sh | sh

# 설치 확인
ollama --version

# 모델 다운로드
ollama pull llama3.1:8b
```

### 3. MQTT 브로커 설치 (최초 1회)

```bash
sudo apt install mosquitto mosquitto-clients -y

# 설정 파일 생성
sudo bash -c 'echo -e "listener 1883\nallow_anonymous true" > /etc/mosquitto/conf.d/sram.conf'

# 부팅 시 자동 시작 + 즉시 시작
sudo systemctl enable --now mosquitto

# 작동 확인
sudo systemctl status mosquitto
```

### 4. PostgreSQL 설치 및 설정 (최초 1회)

```bash
sudo apt install postgresql postgresql-contrib -y
sudo systemctl enable --now postgresql

# DB 및 유저 생성
sudo -u postgres psql <<EOF
CREATE USER sram_user WITH PASSWORD '비밀번호설정';
CREATE DATABASE sram OWNER sram_user;
EOF

# 접속 확인
psql -h localhost -U sram_user -d sram
```

> 테이블은 서버 최초 실행 시 자동 생성됨 (따로 스키마 실행 안해도 됨)

### 5. Python 환경 설정 및 환경변수 (최초 1회)

```bash
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn httpx ollama paho-mqtt websockets 'uvicorn[standard]' psycopg2-binary

# 환경변수 설정
cp .env.example .env
nano .env
```

**env 파일 — 실제 IP로 수정**

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

### 6. 서버 실행

**터미널 1 — Ollama**
```bash
ollama serve
```

**터미널 2 — LLM 서버**
```bash
cd ~/sram_LLM
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000
```

> `--host 0.0.0.0` 필수 — Tier3에서 이 서버로 접근하려면 모든 IP 허용해야 함

### 7. 작동 확인

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"data": {"error_type": "collision", "force_x_max": 150}}'
```

DB에 저장됐는지 확인:
```bash
psql -h localhost -U sram_user -d sram -c "SELECT * FROM threat_logs ORDER BY timestamp DESC LIMIT 5;"
```

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

## Raspberry Pi에서 이 서버로 데이터 보내는 방법

Raspberry Pi(Tier2)가 ESP32로부터 받은 센서 데이터를 LLM 서버로 전송.
LLM이 분석 후 결과를 Tier3 백엔드로 자동 전달함.

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

> 분석 결과는 `server.py`의 `notify_dashboard()`가 자동으로 Tier3에 전달함 (`.env`의 `DASHBOARD_URL` 참고)

---

## 데이터베이스 (PostgreSQL)

### 구현 완료
- 서버 시작 시 `threat_logs` 테이블 자동 생성
- `/analyze` 호출마다 위협 분석 결과 자동 저장
- DB 연결 실패 해도 서버는 정상 작동 (Mac 개발 환경에서는 DB 없어도 됨)

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
- 저장된 로그 조회 API (`GET /logs`) — 혼자서 정하기는 좀 그래서 미구현

---

## LLM 파인튜닝 (우분투에서 추후 작업)

현재는 `llama3.1:8b` 기반으로 동작.
RTX 4070 Ubuntu 서버에서 실제 데이터로 파인튜닝할 계획.

**학습 데이터:**
- `training_data/train.jsonl` — 6,653개 샘플
- `training_data/valid.jsonl` — 740개 샘플
- 데이터 출처: UCI Robot Failures + AI4I 2020 + NIST UR5

### 파인튜닝 전체 파이프라인

```
파인튜닝 (finetune_ubuntu.py)
        │
        ▼
어댑터 병합 (merge_adapter.py)
        │
        ▼
GGUF 변환 (llama.cpp)
        │
        ▼
양자화 Q4_K_M (llama-quantize)
        │
        ▼
Ollama 등록 (ollama create sram-ai)
```

### 1. 사전 준비

```bash
# HuggingFace 로그인 (Llama 3.1 라이선스 동의 후 토큰 발급 필요)
pip install huggingface_hub
huggingface-cli login

# 의존성 설치
pip install transformers datasets peft trl torch accelerate bitsandbytes
```

### 2. 파인튜닝 실행

```bash
python3 finetune_ubuntu.py
# 완료 시 sram_adapter/ 에 LoRA 어댑터 저장됨
```

### 3. 어댑터 병합

```bash
python3 merge_adapter.py
# 완료 시 sram_model_merged/ 에 병합된 모델 저장됨
```

### 4. GGUF 변환 및 양자화

```bash
# llama.cpp 설치
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && pip install -r requirements.txt

# GGUF 변환
python3 convert_hf_to_gguf.py ../sram_model_merged/ --outtype f16 --outfile ../sram_model_f16.gguf

# Q4_K_M 양자화 (6GB → 약 2GB)
llama-quantize ../sram_model_f16.gguf ../sram_model_q4.gguf Q4_K_M
```

### 5. Ollama 등록 및 모델 교체

```bash
# Ollama에 등록
ollama create sram-ai -f Modelfile

# .env 에서 모델 교체
LLM_MODEL=sram-ai
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

---

## 기술 스택

### 서버
| 기술 | 용도 |
|------|------|
| FastAPI | REST API 서버 프레임워크 |
| Uvicorn | ASGI 서버 (FastAPI 실행) |
| Ollama | 로컬 LLM 실행 엔진 |
| llama3.1:8b | 위협 분석 LLM 모델 |
| paho-mqtt | MQTT 긴급정지 명령 전송 |
| httpx | 대시보드 HTTP 알림 전송 |
| psycopg2 | PostgreSQL 연결 |
| PostgreSQL | 위협 분석 로그 저장 |

### 파인튜닝
| 기술 | 용도 |
|------|------|
| transformers | HuggingFace 모델 로드/저장 |
| peft | LoRA 어댑터 적용 |
| trl | SFTTrainer (파인튜닝 학습 루프) |
| bitsandbytes | 4bit 양자화 (QLoRA) |
| datasets | JSONL 학습 데이터 로드 |
| llama.cpp | GGUF 변환 및 양자화 |
