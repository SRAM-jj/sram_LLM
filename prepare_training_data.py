import json
import csv
import ast
import random
import os

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

DATASHEET_DIR = os.path.join(os.path.dirname(__file__), "datasheet")

JOINT_NAMES = ["base", "shoulder", "elbow", "wrist", "gripper"]

LP_FILES = {
    "lp1.data.txt": "Approach to Grip Failure",
    "lp2.data.txt": "Transfer Failure",
    "lp3.data.txt": "Unloading Failure",
    "lp4.data.txt": "Grip Release Failure",
    "lp5.data.txt": "Move Failure",
}

DEVICE_IDS = ["ARM_NODE_01", "ARM_NODE_02", "ARM_NODE_03"]


def get_threat_level(max_effort, max_temp):
    """절대기준 JSON 기반 위협 레벨 판단 (sram_router 기준)"""
    if max_temp > 45 or max_effort > 50:
        return "ERROR"
    elif max_temp > 40 or max_effort > 30:
        return "DANGER"
    else:
        return "WARNING"


def level_to_state(level):
    return {"WARNING": "Warning", "DANGER": "Danger", "ERROR": "Error"}[level]


def make_router_json(device_id, efforts, temperatures, level):
    """절대기준 JSON 포맷 생성"""
    state = level_to_state(level)
    return {
        "device_id": device_id,
        "timestamp": random.randint(1700000000, 1800000000),
        "status": {
            "state": state,
            "error_code": random.randint(1000, 9999) if level != "WARNING" else 0,
            "emergency_stop": level == "ERROR"
        },
        "joints": {
            "names": JOINT_NAMES,
            "positions": [round(random.uniform(-1.57, 1.57), 2) for _ in range(5)],
            "efforts": [round(e, 2) for e in efforts],
            "temperatures": [round(t, 2) for t in temperatures]
        },
        "end_effector": {
            "pose": {
                "x": round(random.uniform(100, 400), 1),
                "y": round(random.uniform(-200, 200), 1),
                "z": round(random.uniform(50, 500), 1),
                "roll": 0.0, "pitch": round(random.uniform(0, 1.57), 2), "yaw": 0.0
            },
            "gripper_active": random.choice([True, False])
        }
    }


def make_sample(input_data, level, cause, action):
    output_data = {"threat": True, "level": level, "cause": cause, "action": action}
    return {
        "messages": [
            {"role": "user", "content": f"Analyze the following robot arm joint data and determine the threat level.\nInput: {json.dumps(input_data)}"},
            {"role": "assistant", "content": json.dumps(output_data)}
        ]
    }


# ── lp1~lp5 파싱 ──────────────────────────────────────────────
def parse_lp_files():
    samples = []
    for filename, failure_type in LP_FILES.items():
        filepath = os.path.join(DATASHEET_DIR, filename)
        current_label = None
        current_readings = []

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                try:
                    list(map(int, parts))
                    current_readings.append(list(map(int, parts)))
                except ValueError:
                    if current_label is not None and current_readings:
                        samples.append({
                            "label": current_label,
                            "readings": current_readings,
                            "failure_type": failure_type
                        })
                    current_label = line
                    current_readings = []

        if current_label is not None and current_readings:
            samples.append({
                "label": current_label,
                "readings": current_readings,
                "failure_type": failure_type
            })
    return samples


def lp_to_training(samples):
    """
    lp1~5: 6채널 (Fx, Fy, Fz, Tx, Ty, Tz) → 절대기준 JSON 포맷으로 변환
    force/torque 값을 5개 관절 efforts로 분배 (shoulder에 최대값 배치)
    온도는 레벨에 맞는 범위로 추정 (실제 온도 데이터 없음)
    """
    data = []
    for s in samples:
        if s["label"] == "normal":
            continue

        readings = s["readings"]
        # 채널: Fx(0), Fy(1), Fz(2), Tx(3), Ty(4), Tz(5)
        force_vals  = [abs(r[0]) for r in readings]
        torque_vals = [abs(r[3]) for r in readings]

        max_force  = max(force_vals)
        max_torque = max(torque_vals)

        # force → effort 스케일 변환 (lp 단위 → Nm 근사)
        # shoulder에 최대값, 나머지는 비례 분배
        scale = 0.3
        efforts = [
            round(max_force * scale * 0.4, 2),   # base
            round(max_force * scale, 2),           # shoulder (최대 부하)
            round(max_torque * scale * 0.8, 2),   # elbow
            round(max_torque * scale * 0.5, 2),   # wrist
            round(max_force * scale * 0.2, 2),    # gripper
        ]

        max_effort = max(efforts)

        # 온도 추정 (레벨별 범위)
        if max_effort > 50:
            temp_range = (44, 60)
        elif max_effort > 30:
            temp_range = (39, 45)
        else:
            temp_range = (28, 40)

        temperatures = [round(random.uniform(*temp_range), 1) for _ in range(5)]
        max_temp = max(temperatures)

        level = get_threat_level(max_effort, max_temp)

        if level == "WARNING":
            cause = f"Moderate {s['label']} during {s['failure_type']}. Shoulder effort at {max_effort:.1f} Nm."
            action = "Monitor continuously and log for trend analysis."
        elif level == "DANGER":
            cause = f"High effort ({max_effort:.1f} Nm) detected during {s['failure_type']}. Risk of joint damage."
            action = "Reduce speed and payload. Inspect joint mechanisms."
        else:
            cause = f"Critical effort ({max_effort:.1f} Nm) during {s['failure_type']}. Risk of permanent damage."
            action = "EMERGENCY STOP. Disconnect power and perform full system diagnostic."

        input_data = make_router_json(random.choice(DEVICE_IDS), efforts, temperatures, level)
        data.append(make_sample(input_data, level, cause, action))
    return data


# ── AI4I 2020 파싱 ─────────────────────────────────────────────
def ai4i_to_training():
    """
    AI4I: torque_Nm → shoulder effort, process_temp_K → °C 변환 후 온도로 사용
    """
    data = []
    filepath = os.path.join(os.path.dirname(__file__), "ai4i2020.csv")

    failure_map = {
        "TWF": ("DANGER",  "Tool wear failure. Joint torque exceeded safe operating limit.",          "Replace worn components and inspect joint mechanisms."),
        "HDF": ("DANGER",  "Heat dissipation failure. Joint temperature critically high.",            "Stop operation, check cooling system and reduce speed."),
        "PWF": ("ERROR",   "Power failure. Motor operating outside safe torque envelope.",            "EMERGENCY STOP. Inspect motor and power supply immediately."),
        "OSF": ("ERROR",   "Overstrain failure. Joint torque exceeded structural limit.",             "EMERGENCY STOP. Reduce torque settings and inspect mechanical components."),
        "RNF": ("WARNING", "Random anomaly detected. Cause undetermined.",                           "Log the event, monitor for recurrence, and schedule maintenance."),
    }

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            active = next((ft for ft in ["TWF", "HDF", "PWF", "OSF", "RNF"] if int(row[ft]) == 1), None)
            if not active:
                continue

            level, cause, action = failure_map[active]

            torque_nm   = float(row["Torque [Nm]"])
            process_temp_c = float(row["Process temperature [K]"]) - 273.15

            # torque → 5개 관절 efforts 분배 (shoulder 최대)
            efforts = [
                round(torque_nm * 0.4, 2),
                round(torque_nm, 2),         # shoulder 최대
                round(torque_nm * 0.7, 2),
                round(torque_nm * 0.4, 2),
                round(torque_nm * 0.1, 2),
            ]

            # process_temp → 관절 온도 분배 (shoulder 가장 높음)
            temperatures = [
                round(process_temp_c * 0.85, 1),
                round(process_temp_c, 1),    # shoulder 최대
                round(process_temp_c * 0.9, 1),
                round(process_temp_c * 0.8, 1),
                round(process_temp_c * 0.75, 1),
            ]

            # 레벨 재검증 (규칙 기반 보정)
            max_effort = max(efforts)
            max_temp   = max(temperatures)
            level = get_threat_level(max_effort, max_temp)

            input_data = make_router_json(random.choice(DEVICE_IDS), efforts, temperatures, level)
            data.append(make_sample(input_data, level, cause, action))
    return data


# ── UR5 파싱 (5% 샘플링) ──────────────────────────────────────
def ur5_to_training(sample_rate=0.05):
    """
    UR5: actual_moment(6관절 토크) → efforts, joint_temps → temperatures
    절대기준 JSON과 가장 자연스럽게 매핑되는 데이터
    """
    data = []
    ur5_files = [f for f in os.listdir(DATASHEET_DIR) if f.startswith("ur5testresult") and f.endswith(".csv")]

    for filename in ur5_files:
        filepath = os.path.join(DATASHEET_DIR, filename)
        condition = filename.replace("ur5testresult_", "").replace(".csv", "")

        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or random.random() > sample_rate:
                    continue
                try:
                    row = ast.literal_eval(line)
                    if len(row) < 13:
                        continue

                    actual_moment = row[10]   # 6관절 토크 [Nm]
                    joint_temps   = row[12]   # 6관절 온도 [°C]

                    # UR5는 6관절 → 첫 5개 사용 (JOINT_NAMES에 맞춤)
                    efforts      = [round(abs(t), 2) for t in actual_moment[:5]]
                    temperatures = [round(t, 2) for t in joint_temps[:5]]

                    max_effort = max(efforts)
                    max_temp   = max(temperatures)
                    level      = get_threat_level(max_effort, max_temp)

                    if level == "ERROR":
                        cause  = f"Critical joint torque ({max_effort:.1f} Nm) or temperature ({max_temp:.1f}°C) exceeded safe limits during {condition}."
                        action = "EMERGENCY STOP. Cool down joints and inspect mechanical components."
                    elif level == "DANGER":
                        cause  = f"High joint torque ({max_effort:.1f} Nm) or temperature ({max_temp:.1f}°C) approaching critical limits during {condition}."
                        action = "Reduce speed and payload. Monitor temperature continuously."
                    else:
                        cause  = f"Elevated joint torque ({max_effort:.1f} Nm) detected during {condition} operation."
                        action = "Monitor system and log for trend analysis."

                    input_data = make_router_json(random.choice(DEVICE_IDS), efforts, temperatures, level)
                    data.append(make_sample(input_data, level, cause, action))
                except Exception:
                    continue
    return data


# ── UR3 CobotOps 파싱 ─────────────────────────────────────────
def ur3_cobotops_to_training(normal_sample_rate=0.05):
    """
    UR3 CobotOps (UCI): 관절별 전류(Current) + 온도(Temperature) → 절대기준 JSON 포맷
    - Robot_ProtectiveStop = 1 → ERROR (로봇 안전 정지 발생)
    - grip_lost = True        → DANGER (그립 손실)
    - 정상 샘플               → 5% 샘플링 후 규칙 기반 레벨 판정
    전류(A) × 7 → 토크 추정값(Nm)
    """
    if not HAS_PANDAS:
        print("⚠️ pandas 미설치 — UR3 CobotOps 건너뜀 (pip install pandas openpyxl)")
        return []

    filepath = os.path.join(DATASHEET_DIR, "ur3_cobotops", "dataset_02052023.xlsx")
    if not os.path.exists(filepath):
        print("⚠️ UR3 CobotOps 파일 없음 — 건너뜀")
        return []

    df = pd.read_excel(filepath)
    data = []
    CURRENT_TO_NM = 7.0  # 전류(A) → 토크 추정(Nm) 변환 계수

    for _, row in df.iterrows():
        protective_stop = row["Robot_ProtectiveStop"] == 1.0
        grip_lost       = row["grip_lost"] == True

        # 정상 샘플은 샘플링
        if not protective_stop and not grip_lost:
            if random.random() > normal_sample_rate:
                continue

        # 관절 전류 → efforts (J0~J4, 5개 관절)
        efforts = [
            round(abs(row["Current_J0"]) * CURRENT_TO_NM, 2),
            round(abs(row["Current_J1"]) * CURRENT_TO_NM, 2),
            round(abs(row["Current_J2"]) * CURRENT_TO_NM, 2),
            round(abs(row["Current_J3"]) * CURRENT_TO_NM, 2),
            round(abs(row["Current_J4"]) * CURRENT_TO_NM, 2),
        ]

        # 관절 온도 (T0, J1~J4)
        temperatures = [
            round(float(row["Temperature_T0"]), 2),
            round(float(row["Temperature_J1"]), 2),
            round(float(row["Temperature_J2"]), 2),
            round(float(row["Temperature_J3"]), 2),
            round(float(row["Temperature_J4"]), 2),
        ]

        max_effort = max(efforts)
        max_temp   = max(temperatures)

        # 레이블 기반 레벨 결정 (규칙 기반 보정보다 레이블 우선)
        if protective_stop:
            level  = "ERROR"
            cause  = f"Protective stop triggered. Joint current exceeded safe limits (max effort: {max_effort:.1f} Nm)."
            action = "EMERGENCY STOP. Inspect all joints and check for mechanical obstruction."
        elif grip_lost:
            level  = "DANGER"
            cause  = f"Grip lost during operation. Excessive joint load detected (max effort: {max_effort:.1f} Nm, max temp: {max_temp:.1f}°C)."
            action = "Stop operation immediately. Inspect gripper mechanism and reduce payload."
        else:
            level  = get_threat_level(max_effort, max_temp)
            cause  = f"Elevated joint temperature ({max_temp:.1f}°C) or torque ({max_effort:.1f} Nm) detected during normal operation."
            action = "Monitor continuously and log for trend analysis."

        input_data = make_router_json(random.choice(DEVICE_IDS), efforts, temperatures, level)
        data.append(make_sample(input_data, level, cause, action))

    return data


# ── 메인 ──────────────────────────────────────────────────────
def main():
    print("데이터 변환 시작 (절대기준 JSON 포맷)...\n")

    lp_data   = lp_to_training(parse_lp_files())
    ai4i_data = ai4i_to_training()
    ur5_data  = ur5_to_training(sample_rate=0.05)
    ur3_data  = ur3_cobotops_to_training(normal_sample_rate=0.05)

    print(f"lp 데이터:        {len(lp_data)}개")
    print(f"AI4I 데이터:      {len(ai4i_data)}개")
    print(f"UR5 데이터:       {len(ur5_data)}개")
    print(f"UR3 CobotOps:     {len(ur3_data)}개")

    all_data = lp_data + ai4i_data + ur5_data + ur3_data
    random.shuffle(all_data)

    split      = int(len(all_data) * 0.9)
    train_data = all_data[:split]
    valid_data = all_data[split:]

    output_dir = os.path.join(os.path.dirname(__file__), "training_data")
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "train.jsonl"), 'w') as f:
        for item in train_data:
            f.write(json.dumps(item) + '\n')

    with open(os.path.join(output_dir, "valid.jsonl"), 'w') as f:
        for item in valid_data:
            f.write(json.dumps(item) + '\n')

    print(f"\n완료!")
    print(f"총 {len(all_data)}개 샘플")
    print(f"훈련: {len(train_data)}개 → training_data/train.jsonl")
    print(f"검증: {len(valid_data)}개 → training_data/valid.jsonl")


if __name__ == "__main__":
    main()
