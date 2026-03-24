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
            
            # 레이블 줄: normal 또는 failure 텍스트
            try:
                list(map(int, parts))
                # 숫자줄 → 센서값
                current_readings.append(list(map(int, parts)))
            except ValueError:
                # 텍스트줄 → 레이블
                if current_label is not None and current_readings:
                    samples.append({
                        "label": current_label,
                        "readings": current_readings,
                        "failure_type": failure_type
                    })
                current_label = line
                current_readings = []
    
    # 마지막 샘플
    if current_label is not None and current_readings:
        samples.append({
            "label": current_label,
            "readings": current_readings,
            "failure_type": failure_type
        })
    
    return samples

files = {
    "lp1.data.txt": "Approach to Grip Failure",
    "lp2.data.txt": "Transfer Failure",
    "lp3.data.txt": "Unloading Failure",
    "lp4.data.txt": "Grip Release Failure",
    "lp5.data.txt": "Move Failure",
}

all_samples = []
for filename, failure_type in files.items():
    samples = parse_robot_data(filename, failure_type)
    all_samples.extend(samples)
    print(f"{failure_type}: {len(samples)}개")

failures = [s for s in all_samples if s["label"] != "normal"]
normals = [s for s in all_samples if s["label"] == "normal"]

print(f"\n총 오류 샘플: {len(failures)}개")
print(f"총 정상 샘플: {len(normals)}개")
print(f"\n오류 샘플 예시:")
import json
print(json.dumps(failures[0], indent=2))