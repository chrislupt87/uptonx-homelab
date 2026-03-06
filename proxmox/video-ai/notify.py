"""Frigate MQTT event listener — logs events, extensible for notifications."""
import json
import os
import logging
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('frigate-notify')

MQTT_HOST = os.environ.get('MQTT_HOST', '192.168.1.18')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 1883))
FRIGATE_URL = os.environ.get('FRIGATE_URL', 'http://192.168.1.18:5000')

def on_connect(client, userdata, flags, rc, properties=None):
    log.info('Connected to MQTT broker (rc=%s)', rc)
    client.subscribe('frigate/events')
    client.subscribe('frigate/reviews')

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        topic = msg.topic
        if topic == 'frigate/events':
            etype = payload.get('type', '?')
            after = payload.get('after', {})
            label = after.get('label', '?')
            camera = after.get('camera', '?')
            score = after.get('top_score', 0)
            sub_label = after.get('sub_label')
            face_info = f' [{sub_label}]' if sub_label else ''
            log.info('EVENT %s: %s%s on %s (score=%.2f)', etype, label, face_info, camera, score)
        elif topic == 'frigate/reviews':
            log.info('REVIEW: %s', json.dumps(payload)[:200])
    except Exception as e:
        log.error('Error processing message: %s', e)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
log.info('Connecting to MQTT %s:%s', MQTT_HOST, MQTT_PORT)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_forever()
