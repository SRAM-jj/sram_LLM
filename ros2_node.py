"""
S.RAM! ROS 2 수신 노드 (llm_analyzer_node)

Raspberry Pi 라우터로부터 ROS 2 토픽을 구독해 LLM 서버로 전달.
sram_router의 filter_node가 분류한 데이터를 수신함.

구독 토픽:
- /alert_error  : ERROR 상태 즉시 전송
- /alert_danger : DANGER 상태 즉시 전송
- /safe_bulk_data : SAFE 상태 10초 단위 배치 전송 (분석 생략)

실행 방법:
    # ROS 2 환경 활성화 후
    export ROS_DOMAIN_ID=30
    python3 ros2_node.py

절대기준 JSON 포맷 (sram_router 기준):
{
  "device_id": "ARM_NODE_01",
  "timestamp": 123456789,
  "status": {"state": "ERROR", "error_code": 4021, "emergency_stop": true},
  "joints": {
    "names": ["base", "shoulder", "elbow", "wrist", "gripper"],
    "positions": [1.57, -0.52, 1.20, 0.0, 0.5],
    "efforts": [12.5, 210.5, 30.1, 5.0, 1.2],
    "temperatures": [35.2, 88.3, 38.0, 32.1, 30.0]
  },
  "end_effector": {
    "pose": {"x": 250.5, "y": 100.2, "z": 300.0, "roll": 0.0, "pitch": 1.57, "yaw": 0.0},
    "gripper_active": true
  }
}
"""

import os
import json
import logging
import httpx
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

LLM_SERVER_URL = os.getenv("LLM_SERVER_URL", "http://localhost:8000/analyze")
LLM_API_KEY    = os.getenv("API_KEY", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("S.RAM! ROS2")


class LLMAnalyzerNode(Node):
    def __init__(self):
        super().__init__("llm_analyzer_node")

        # ERROR/DANGER 즉시 전송 토픽 구독
        self.create_subscription(String, "/alert_error",  self.on_alert, 10)
        self.create_subscription(String, "/alert_danger", self.on_alert, 10)

        # SAFE 배치 데이터 (분석 생략, 로그만)
        self.create_subscription(String, "/safe_bulk_data", self.on_safe, 10)

        self.get_logger().info("✅ llm_analyzer_node 시작 — /alert_error, /alert_danger 구독 중")

    def on_alert(self, msg: String):
        try:
            data = json.loads(msg.data)
            device_id = data.get("device_id", "unknown")
            state = data.get("status", {}).get("state", "unknown")
            self.get_logger().info(f"📨 수신: {device_id} / state={state}")

            headers = {"X-API-Key": LLM_API_KEY} if LLM_API_KEY else {}
            response = httpx.post(
                LLM_SERVER_URL,
                json={"data": data},
                headers=headers,
                timeout=30
            )
            result = response.json()
            self.get_logger().info(f"🧠 분석 결과: level={result.get('level')} / {result.get('cause')}")

        except json.JSONDecodeError:
            self.get_logger().error("⚠️ JSON 파싱 실패")
        except Exception as e:
            self.get_logger().error(f"⚠️ LLM 서버 전송 실패: {e}")

    def on_safe(self, msg: String):
        try:
            data = json.loads(msg.data)
            device_id = data.get("device_id", "unknown")
            self.get_logger().info(f"📦 SAFE 배치 수신: {device_id} (분석 생략)")
        except Exception:
            pass


def main():
    rclpy.init()
    node = LLMAnalyzerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
