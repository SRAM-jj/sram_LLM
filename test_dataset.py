import csv
import httpx
import json
import time

CSV_PATH = "/Users/jihun/Desktop/ai4i2020.csv"
API_URL = "http://127.0.0.1:8000/analyze"

# 오류 유형 매핑
FAILURE_TYPES = {
    "TWF": "Tool Wear Failure",
    "HDF": "Heat Dissipation Failure",
    "PWF": "Power Failure",
    "OSF": "Overstrain Failure",
    "RNF": "Random Failure"
}

def parse_failure_type(row):
    for key in FAILURE_TYPES:
        if row[key] == "1":
            return FAILURE_TYPES[key]
    return "Unknown"

def csv_to_sram_json(row):
    return {
        "data": {
            "error_type": parse_failure_type(row),
            "machine_id": row["Product ID"],
            "type": row["Type"],
            "air_temp_K": float(row["Air temperature [K]"]),
            "process_temp_K": float(row["Process temperature [K]"]),
            "rotational_speed_rpm": int(row["Rotational speed [rpm]"]),
            "torque_Nm": float(row["Torque [Nm]"]),
            "tool_wear_min": int(row["Tool wear [min]"]),
            "machine_failure": int(row["Machine failure"])
        }
    }

def main():
    with open(CSV_PATH, newline='') as f:
        reader = csv.DictReader(f)
        
        # 오류 데이터만 필터링 (Machine failure == 1)
        failures = [row for row in reader if row["Machine failure"] == "1"]
    
    print(f"총 오류 데이터: {len(failures)}개\n")
    
    # 처음 5개만 테스트
    for i, row in enumerate(failures[:5]):
        payload = csv_to_sram_json(row)
        print(f"--- [{i+1}] {payload['data']['machine_id']} ---")
        print(f"입력: {json.dumps(payload['data'], indent=2)}")
        
        response = httpx.post(API_URL, json=payload, timeout=60)
        result = response.json()
        print(f"LLM 판단: {json.dumps(result, indent=2, ensure_ascii=False)}\n")
        
        time.sleep(1)  # 요청 간격

if __name__ == "__main__":
    main()