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


def generate_cause_action(efforts, temperatures, level, context=""):
    """관절별 구체적 원인 분석 및 단계별 조치 생성"""
    max_e_idx = efforts.index(max(efforts))
    max_t_idx = temperatures.index(max(temperatures))
    max_e = efforts[max_e_idx]
    max_t = temperatures[max_t_idx]
    e_joint = JOINT_NAMES[max_e_idx]
    t_joint = JOINT_NAMES[max_t_idx]

    high_torque = max_e > 30
    high_temp = max_t > 40

    if level == "ERROR":
        causes = [
            f"Critical overload on {e_joint} joint: torque {max_e:.1f} Nm far exceeds safe limit (50 Nm). {t_joint} joint temperature at {max_t:.1f}°C. Likely cause: collision with obstacle or mechanical seizure.",
            f"Emergency condition detected. {e_joint} joint torque ({max_e:.1f} Nm) indicates possible collision or structural failure. {t_joint} joint thermal stress at {max_t:.1f}°C suggests motor overload.",
            f"Severe anomaly on {e_joint} joint ({max_e:.1f} Nm). Combined with {t_joint} joint temperature of {max_t:.1f}°C, this indicates potential mechanical binding, payload overload, or gearbox failure.",
        ]
        actions = [
            f"EMERGENCY STOP immediately. 1) Disconnect power to {e_joint} joint. 2) Clear workspace and inspect for collision damage. 3) Wait for {t_joint} joint to cool below 35°C. 4) Check {e_joint} gearbox and motor windings for damage. 5) Run full calibration before resuming.",
            f"EMERGENCY STOP. 1) Power off all joint motors. 2) Inspect {e_joint} joint for mechanical obstruction or damage. 3) Verify payload weight does not exceed rated capacity. 4) Check {t_joint} joint cooling system. 5) Perform full system diagnostic before restart.",
            f"EMERGENCY STOP required. 1) Isolate {e_joint} joint from power. 2) Document current joint positions and sensor readings. 3) Inspect {e_joint} for physical damage or foreign objects. 4) Check {t_joint} bearing lubrication. 5) Do not resume until maintenance confirms safe operation.",
        ]
    elif level == "DANGER":
        if high_torque and high_temp:
            causes = [
                f"High load on {e_joint} joint ({max_e:.1f} Nm) approaching critical threshold. {t_joint} joint temperature ({max_t:.1f}°C) rising dangerously. Risk of permanent joint damage if operation continues.",
                f"Dual risk detected: {e_joint} joint torque at {max_e:.1f} Nm and {t_joint} joint temperature at {max_t:.1f}°C both trending toward critical levels. Possible cause: excessive payload or prolonged high-duty operation.",
            ]
            actions = [
                f"1) Reduce operating speed by 50% immediately. 2) Decrease payload if possible. 3) Monitor {e_joint} torque and {t_joint} temperature every 30 seconds. 4) If {t_joint} exceeds 43°C, initiate controlled shutdown. 5) Schedule {e_joint} joint maintenance inspection.",
                f"1) Slow robot to minimum operational speed. 2) Check {e_joint} joint for unusual vibration or noise. 3) Allow {t_joint} joint 5-minute cooling period between cycles. 4) Log all sensor readings for trend analysis. 5) Prepare for controlled shutdown if values increase.",
            ]
        elif high_torque:
            causes = [
                f"Elevated torque on {e_joint} joint ({max_e:.1f} Nm) approaching danger threshold. Potential causes: increased friction in joint mechanism, partial workspace obstruction, or payload shift during operation.",
                f"{e_joint} joint torque ({max_e:.1f} Nm) significantly above normal operating range. May indicate mechanical wear, misalignment, or gradual bearing degradation.",
            ]
            actions = [
                f"1) Reduce speed and payload immediately. 2) Verify {e_joint} joint workspace is clear. 3) Monitor {e_joint} torque trend for next 5 minutes. 4) Check joint lubrication and mechanical alignment. 5) If torque does not decrease, perform controlled stop.",
                f"1) Decrease operational speed by 30-50%. 2) Inspect {e_joint} joint for signs of wear or damage. 3) Verify payload is properly secured and within limits. 4) Schedule preventive maintenance for {e_joint} joint. 5) Initiate shutdown if torque exceeds 45 Nm.",
            ]
        else:
            causes = [
                f"Elevated temperature on {t_joint} joint ({max_t:.1f}°C) approaching critical threshold (45°C). Likely cause: sustained high-duty operation without adequate cooling or early bearing degradation.",
                f"{t_joint} joint temperature ({max_t:.1f}°C) above normal operating range. Possible causes: insufficient cooling airflow, high ambient temperature, or increased internal friction.",
            ]
            actions = [
                f"1) Reduce operation duty cycle immediately. 2) Allow {t_joint} joint 5-minute cooling between cycles. 3) Check ventilation and cooling system around {t_joint} joint. 4) Monitor temperature trend. 5) Initiate controlled shutdown if temperature exceeds 43°C.",
                f"1) Lower operating speed to reduce heat generation. 2) Verify {t_joint} joint cooling fan is operational. 3) Check ambient temperature and improve ventilation if possible. 4) Inspect {t_joint} bearings for excess friction. 5) Schedule thermal inspection.",
            ]
    else:  # WARNING
        torque_concern = max_e > max_t * 0.4
        if torque_concern:
            causes = [
                f"Moderate torque increase on {e_joint} joint ({max_e:.1f} Nm). Within safe limits but above normal baseline. May indicate early signs of mechanical wear or slight payload imbalance.",
                f"Minor torque anomaly detected on {e_joint} joint ({max_e:.1f} Nm). All values within operational limits. Could be caused by payload variation, surface friction change, or normal wear progression.",
                f"{e_joint} joint showing elevated effort ({max_e:.1f} Nm) compared to typical operation. No immediate risk, but pattern may indicate developing mechanical issue.",
            ]
            actions = [
                f"1) Log {e_joint} joint torque for trend analysis. 2) Monitor over next operating hour. 3) Verify payload alignment and weight. 4) Schedule preventive maintenance if upward trend continues.",
                f"1) Record current sensor readings. 2) Compare {e_joint} joint torque with historical baseline. 3) Check payload securing mechanism. 4) Continue normal operation with increased monitoring frequency.",
                f"1) Continue operation with monitoring. 2) Track {e_joint} joint torque readings over next 10 cycles. 3) Flag for maintenance review if readings increase by more than 10%. 4) Verify work environment conditions.",
            ]
        else:
            causes = [
                f"Slight temperature elevation on {t_joint} joint ({max_t:.1f}°C). Within safe operating range but trending upward. May indicate increased operational load or ambient temperature change.",
                f"Minor thermal increase detected on {t_joint} joint ({max_t:.1f}°C). No immediate concern. Possible causes: higher duty cycle, ambient conditions, or gradual bearing wear.",
                f"{t_joint} joint temperature ({max_t:.1f}°C) slightly above normal baseline. All joints operating within safe limits. Routine monitoring recommended.",
            ]
            actions = [
                f"1) Log {t_joint} joint temperature for trend analysis. 2) Monitor over next operating cycle. 3) Check ambient temperature and cooling airflow. 4) Schedule bearing inspection if trend persists.",
                f"1) Record temperature readings for analysis. 2) Verify {t_joint} joint cooling is unobstructed. 3) Continue normal operation. 4) Review temperature logs at end of shift.",
                f"1) Continue operation with routine monitoring. 2) Track {t_joint} temperature over next hour. 3) Ensure adequate ventilation around robot arm. 4) No immediate action required.",
            ]

    cause = random.choice(causes)
    action = random.choice(actions)

    if context:
        cause += f" {context}"

    return cause, action


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

        cause, action = generate_cause_action(
            efforts, temperatures, level,
            context=f"Detected during {s['failure_type']} ({s['label']})."
        )

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

            cause, action = generate_cause_action(
                efforts, temperatures, level,
                context=f"Failure type: {active} (AI4I predictive maintenance)."
            )

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

                    cause, action = generate_cause_action(
                        efforts, temperatures, level,
                        context=f"Condition: {condition} (UR5 test data)."
                    )

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
            level = "ERROR"
            ctx = "Robot protective stop triggered (UR3 CobotOps)."
        elif grip_lost:
            level = "DANGER"
            ctx = "Grip lost during operation. Gripper mechanism failure detected (UR3 CobotOps)."
        else:
            level = get_threat_level(max_effort, max_temp)
            ctx = "Normal operation monitoring (UR3 CobotOps)."

        cause, action = generate_cause_action(efforts, temperatures, level, context=ctx)

        input_data = make_router_json(random.choice(DEVICE_IDS), efforts, temperatures, level)
        data.append(make_sample(input_data, level, cause, action))

    return data


# ── voraus-AD 파싱 ────────────────────────────────────────────
def voraus_to_training(sample_rate=0.03):
    """
    voraus-AD: motor_torque(5관절) → efforts, temp_est → temperatures
    6-DOF 협동로봇 데이터를 5관절(S.RAM! 기준)으로 변환
    토크 스케일 보정: voraus-AD 로봇 → S.RAM! 로봇 (×0.35)
    이상 샘플: sample_rate 적용, 정상 샘플: sample_rate × 0.1
    """
    if not HAS_PANDAS:
        print("⚠️ pandas 미설치 — voraus-AD 건너뜀")
        return []

    combined_dir = os.path.join(DATASHEET_DIR, "sram_combined")
    if not os.path.exists(combined_dir):
        print("⚠️ sram_combined 디렉토리 없음 — 건너뜀")
        return []

    voraus_files = sorted(
        f for f in os.listdir(combined_dir)
        if f.startswith("voraus_ad_part") and f.endswith(".csv")
    )
    if not voraus_files:
        print("⚠️ voraus-AD 파일 없음 — 건너뜀")
        return []

    TORQUE_SCALE = 0.35  # voraus-AD → S.RAM! 토크 스케일 보정

    needed_cols = (
        [f"motor_torque_{j}" for j in range(1, 6)] +
        [f"temp_est_{j}" for j in range(1, 6)] +
        ["anomaly", "category", "label"]
    )

    data = []
    for filename in voraus_files:
        filepath = os.path.join(combined_dir, filename)
        df = pd.read_csv(filepath, usecols=needed_cols)

        # 이상 샘플과 정상 샘플 분리 샘플링
        anom_df = df[df["label"] != "normal"].sample(
            frac=sample_rate, random_state=42
        )
        norm_df = df[df["label"] == "normal"].sample(
            frac=sample_rate * 0.1, random_state=42
        )
        sampled = pd.concat([anom_df, norm_df])

        for _, row in sampled.iterrows():
            efforts = [
                round(abs(row[f"motor_torque_{j}"]) * TORQUE_SCALE, 2)
                for j in range(1, 6)
            ]
            temperatures = [
                round(row[f"temp_est_{j}"], 2)
                for j in range(1, 6)
            ]

            max_effort = max(efforts)
            max_temp = max(temperatures)

            # voraus-AD 자체 anomaly 레이블 우선 사용 (스케일 차이 보정)
            csv_label = row["label"]
            if csv_label == "error":
                level = "ERROR"
            elif csv_label == "danger":
                level = "DANGER"
            else:
                level = "WARNING"

            category = int(row["category"])

            cause, action = generate_cause_action(
                efforts, temperatures, level,
                context=f"Anomaly pattern {category} during pick-and-place (voraus-AD)."
            )

            input_data = make_router_json(
                random.choice(DEVICE_IDS), efforts, temperatures, level
            )
            data.append(make_sample(input_data, level, cause, action))

        print(f"  {filename}: {len(sampled)}개 샘플")

    return data


# ── 메인 ──────────────────────────────────────────────────────
def main():
    print("데이터 변환 시작 (절대기준 JSON 포맷)...\n")

    lp_data   = lp_to_training(parse_lp_files())
    ai4i_data = ai4i_to_training()
    ur5_data  = ur5_to_training(sample_rate=0.05)
    ur3_data  = ur3_cobotops_to_training(normal_sample_rate=0.05)

    voraus_data = voraus_to_training(sample_rate=0.03)

    print(f"lp 데이터:        {len(lp_data)}개")
    print(f"AI4I 데이터:      {len(ai4i_data)}개")
    print(f"UR5 데이터:       {len(ur5_data)}개")
    print(f"UR3 CobotOps:     {len(ur3_data)}개")
    print(f"voraus-AD:        {len(voraus_data)}개")

    all_data = lp_data + ai4i_data + ur5_data + ur3_data + voraus_data
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
