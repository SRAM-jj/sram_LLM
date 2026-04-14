import os
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt

logger = logging.getLogger("S.RAM!")

MQTT_BROKER   = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC    = os.getenv("MQTT_TOPIC", "sram/emergency_stop")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_TLS  = os.getenv("MQTT_USE_TLS", "false").lower() == "true"


def emergency_stop():
    logger.critical("🛑 로봇 긴급 정지 명령 전송 중...")
    try:
        client = mqtt.Client()
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        if MQTT_USE_TLS:
            client.tls_set()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        payload = json.dumps({
            "command": "EMERGENCY_STOP",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": "ERROR threat detected by S.RAM! AI"
        })
        client.publish(MQTT_TOPIC, payload)
        client.disconnect()
        logger.critical("🛑 긴급 정지 명령 전송 완료!")
    except Exception as e:
        logger.critical(f"🛑 긴급 정지 명령 전송 실패: {e}")
