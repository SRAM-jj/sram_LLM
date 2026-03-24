import httpx
import json
import time
import statistics

API_URL = "http://127.0.0.1:8000/analyze"

def parse_robot_data(filepath, failure_type):
    samples = []
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

def to_sram_json(sample):
    readings = sample["readings"]
    fx = [r[0] for r in readings]
    fy = [r[1] for r in readings]
    fz = [r[2] for r in readings]
    tx = [r[3] for r in readings]
    ty = [r[4] for r in readings]
    tz = [r[5] for r in readings]

    return {
        "data": {
            "error_type": sample["label"],
            "failure_type": sample["failure_type"],
            "force_x_avg": round(statistics.mean(fx), 2),
            "force_y_avg": round(statistics.mean(fy), 2),
            "force_z_avg": round(statistics.mean(fz), 2),
            "torque_x_avg": round(statistics.mean(tx), 2),
            "torque_y_avg": round(statistics.mean(ty), 2),
            "torque_z_avg": round(statistics.mean(tz), 2),
            "force_x_max": max(fx),
            "torque_x_min": min(tx),
            "samples": len(readings)
        }
    }

files = {
    "lp1.data.txt": "Approach to Grip Failure",
    "lp2.data.txt": "Transfer Failure",
    "lp3.data.txt": "Unloading Failure",
    "lp4.data.txt": "Grip Release Failure",
    "lp5.data.txt": "Move Failure",
}

all_failures = []
for filename, failure_type in files.items():
    samples = parse_robot_data(filename, failure_type)
    failures = [s for s in samples if s["label"] != "normal"]
    all_failures.extend(failures)

print(f"총 오류 샘플: {len(all_failures)}개\n")

# 처음 5개 테스트
for i, sample in enumerate(all_failures[:5]):
    payload = to_sram_json(sample)
    print(f"--- [{i+1}] {sample['failure_type']} / {sample['label']} ---")
    print(f"입력: {json.dumps(payload['data'], indent=2)}")

    response = httpx.post(API_URL, json=payload, timeout=60)
    result = response.json()
    print(f"LLM 판단: {json.dumps(result, indent=2, ensure_ascii=False)}\n")
    time.sleep(1)