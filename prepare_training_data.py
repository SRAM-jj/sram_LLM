import json
import csv
import ast
import random
import os

DATASHEET_DIR = os.path.join(os.path.dirname(__file__), "datasheet")

LP_FILES = {
    "lp1.data.txt": "Approach to Grip Failure",
    "lp2.data.txt": "Transfer Failure",
    "lp3.data.txt": "Unloading Failure",
    "lp4.data.txt": "Grip Release Failure",
    "lp5.data.txt": "Move Failure",
}

def get_threat_level(force_x_max):
    val = abs(force_x_max)
    if val < 100:
        return "WARNING"
    elif val < 180:
        return "DANGER"
    else:
        return "ERROR"

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
    data = []
    for s in samples:
        if s["label"] == "normal":
            continue

        readings = s["readings"]
        force_x_values = [r[0] for r in readings]
        torque_x_values = [r[3] for r in readings]

        force_x_max = max(force_x_values)
        force_x_min = min(force_x_values)
        torque_x_min = min(torque_x_values)

        level = get_threat_level(force_x_max)

        if level == "WARNING":
            cause = f"Moderate {s['label']} during {s['failure_type']}, force within manageable range."
            action = "Pause operation and inspect gripper mechanism."
        elif level == "DANGER":
            cause = f"Severe {s['label']} during {s['failure_type']}, dangerously high force detected."
            action = "Immediate shutdown and full mechanical inspection required."
        else:
            cause = f"Critical {s['label']} during {s['failure_type']} with extreme force, risk of permanent damage."
            action = "EMERGENCY STOP. Disconnect power and perform full system diagnostic."

        input_data = {
            "error_type": s["label"],
            "failure_type": s["failure_type"],
            "force_x_max": force_x_max,
            "force_x_min": force_x_min,
            "torque_x_min": torque_x_min
        }
        output_data = {"threat": True, "level": level, "cause": cause, "action": action}

        data.append({
            "messages": [
                {"role": "user", "content": f"Analyze the following robot sensor data and determine the threat level.\nInput: {json.dumps(input_data)}"},
                {"role": "assistant", "content": json.dumps(output_data)}
            ]
        })
    return data

# ── AI4I 2020 파싱 ─────────────────────────────────────────────
def ai4i_to_training():
    data = []
    filepath = os.path.join(os.path.dirname(__file__), "ai4i2020.csv")

    failure_map = {
        "TWF": ("DANGER",  "Tool wear failure, tool life exceeded safe operating limit.",           "Replace tool immediately and inspect workpiece quality."),
        "HDF": ("DANGER",  "Heat dissipation failure, process temperature critically high.",        "Stop operation, check cooling system and reduce rotational speed."),
        "PWF": ("ERROR",   "Power failure, motor operating outside safe power envelope.",           "EMERGENCY STOP. Inspect motor and power supply immediately."),
        "OSF": ("ERROR",   "Overstrain failure, torque exceeded tool strength limit.",              "EMERGENCY STOP. Reduce torque settings and inspect mechanical components."),
        "RNF": ("WARNING", "Random failure detected, cause undetermined.",                         "Log the event, monitor for recurrence, and schedule maintenance."),
    }

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            active = next((ft for ft in ["TWF", "HDF", "PWF", "OSF", "RNF"] if int(row[ft]) == 1), None)
            if not active:
                continue

            level, cause, action = failure_map[active]
            input_data = {
                "error_type": active,
                "air_temp_K": float(row["Air temperature [K]"]),
                "process_temp_K": float(row["Process temperature [K]"]),
                "rotational_speed_rpm": int(row["Rotational speed [rpm]"]),
                "torque_Nm": float(row["Torque [Nm]"]),
                "tool_wear_min": int(row["Tool wear [min]"])
            }
            output_data = {"threat": True, "level": level, "cause": cause, "action": action}

            data.append({
                "messages": [
                    {"role": "user", "content": f"Analyze the following robot sensor data and determine the threat level.\nInput: {json.dumps(input_data)}"},
                    {"role": "assistant", "content": json.dumps(output_data)}
                ]
            })
    return data

# ── UR5 파싱 (5% 샘플링) ──────────────────────────────────────
def ur5_to_training(sample_rate=0.05):
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

                    actual_moment = row[10]
                    joint_temps   = row[12]
                    actual_q      = row[2]
                    target_q      = row[1]

                    max_torque = max(abs(t) for t in actual_moment)
                    max_temp   = max(joint_temps)
                    avg_temp   = sum(joint_temps) / len(joint_temps)
                    pos_error  = max(abs(a - t) for a, t in zip(actual_q, target_q))

                    if max_temp > 45 or max_torque > 50:
                        level  = "ERROR"
                        cause  = f"Critical joint temperature ({max_temp:.1f}°C) or torque ({max_torque:.1f}Nm) exceeded safe limits."
                        action = "EMERGENCY STOP. Cool down joints and inspect mechanical components."
                    elif max_temp > 40 or max_torque > 30:
                        level  = "DANGER"
                        cause  = f"High joint temperature ({max_temp:.1f}°C) or torque ({max_torque:.1f}Nm) approaching critical limits."
                        action = "Reduce speed and payload. Monitor temperature continuously."
                    else:
                        level  = "WARNING"
                        cause  = f"Elevated joint torque ({max_torque:.1f}Nm) detected during {condition} operation."
                        action = "Monitor system and log for trend analysis."

                    input_data = {
                        "error_type": "joint_anomaly",
                        "condition": condition,
                        "max_joint_torque_Nm": round(max_torque, 2),
                        "max_joint_temp_C":    round(max_temp, 2),
                        "avg_joint_temp_C":    round(avg_temp, 2),
                        "max_position_error_deg": round(pos_error, 4)
                    }
                    output_data = {"threat": True, "level": level, "cause": cause, "action": action}

                    data.append({
                        "messages": [
                            {"role": "user", "content": f"Analyze the following robot sensor data and determine the threat level.\nInput: {json.dumps(input_data)}"},
                            {"role": "assistant", "content": json.dumps(output_data)}
                        ]
                    })
                except Exception:
                    continue
    return data

# ── 메인 ──────────────────────────────────────────────────────
def main():
    print("데이터 변환 시작...\n")

    lp_data   = lp_to_training(parse_lp_files())
    ai4i_data = ai4i_to_training()
    ur5_data  = ur5_to_training(sample_rate=0.05)

    print(f"lp 데이터:   {len(lp_data)}개")
    print(f"AI4I 데이터: {len(ai4i_data)}개")
    print(f"UR5 데이터:  {len(ur5_data)}개")

    all_data = lp_data + ai4i_data + ur5_data
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
