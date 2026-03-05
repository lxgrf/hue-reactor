import os
import json
import time
import requests
import urllib3
import threading
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Disable self-signed cert warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HUE_BRIDGE_IP = os.environ.get("HUE_BRIDGE_IP")
HUE_APP_KEY = os.environ.get("HUE_APP_KEY")
TARGET_SENSOR_ID = os.environ.get("TARGET_SENSOR_ID")
# We now support a comma-separated list of target light IDs
TARGET_LIGHT_IDS_RAW = os.environ.get("TARGET_LIGHT_IDS")

if not all([HUE_BRIDGE_IP, HUE_APP_KEY, TARGET_SENSOR_ID, TARGET_LIGHT_IDS_RAW]):
    logger.error("Missing required environment variables.")
    logger.error("Ensure HUE_BRIDGE_IP, HUE_APP_KEY, TARGET_SENSOR_ID, and TARGET_LIGHT_IDS are set.")
    exit(1)

TARGET_LIGHT_IDS = [lid.strip() for lid in TARGET_LIGHT_IDS_RAW.split(",") if lid.strip()]
if not TARGET_LIGHT_IDS:
    logger.error("TARGET_LIGHT_IDS cannot be empty.")
    exit(1)

HEADERS = {
    "hue-application-key": HUE_APP_KEY,
    "Accept": "text/event-stream"
}

is_flashing = False
flash_lock = threading.Lock()

def get_light_state(light_id):
    url = f"https://{HUE_BRIDGE_IP}/clip/v2/resource/light/{light_id}"
    try:
        response = requests.get(url, headers={"hue-application-key": HUE_APP_KEY}, verify=False)
        response.raise_for_status()
        data = response.json().get("data", [])
        if data:
            return data[0]
    except Exception as e:
        logger.error(f"Failed to get light state for {light_id}: {e}")
    return None

def set_light_state(light_id, payload):
    url = f"https://{HUE_BRIDGE_IP}/clip/v2/resource/light/{light_id}"
    try:
        response = requests.put(url, headers={"hue-application-key": HUE_APP_KEY}, json=payload, verify=False)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to set light state for {light_id}: {e}")

def flash_light_sequence():
    global is_flashing
    
    with flash_lock:
        if is_flashing:
            logger.info("Already flashing, ignoring new motion.")
            return
        is_flashing = True
        
    try:
        logger.info("Motion detected! Executing flash sequence...")
        
        # In Hue API v2, lights have a native "signaling" feature that gracefully 
        # handles flashing the light and returning it to its previous state
        # (even if it was originally off).
        payload = {
            "signaling": {
                "signal": "on_off",
                "duration": 2000 # Flash for 2 seconds
            }
        }
        
        for light_id in TARGET_LIGHT_IDS:
            set_light_state(light_id, payload)
            
        logger.info("Flash sequence triggered via Hue native signaling.")
        
    finally:
        # Prevent rapid re-triggering just in case.
        # Match the 2 second duration from the signaling payload
        time.sleep(2.5) 
        with flash_lock:
            is_flashing = False

def listen_for_events():
    url = f"https://{HUE_BRIDGE_IP}/eventstream/clip/v2"
    logger.info(f"Connecting to Hue Bridge Event Stream at {url}...")
    
    while True:
        try:
            # We use stream=True and verify=False to connect to the SSE endpoint
            response = requests.get(url, headers=HEADERS, stream=True, verify=False, timeout=None)
            response.raise_for_status()
            
            logger.info("Connected! Listening for events...")
            
            for line in response.iter_lines():
                if not line:
                    continue
                    
                decoded_line = line.decode('utf-8').strip()
                if decoded_line.startswith('data: '):
                    data_str = decoded_line[6:]
                    try:
                        data = json.loads(data_str)
                        for item in data:
                            if item.get("type") == "update":
                                for val in item.get("data", []):
                                    if val.get("type") == "motion" and val.get("id") == TARGET_SENSOR_ID:
                                        motion_data = val.get("motion", {})
                                        if motion_data.get("motion") is True:
                                            threading.Thread(target=flash_light_sequence).start()
                    except json.JSONDecodeError:
                        pass
        except requests.exceptions.RequestException as e:
            logger.error(f"Connection error: {e}")
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.info("Reconnecting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    listen_for_events()
