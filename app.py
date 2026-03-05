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
        
        # 1. Get current state for each light
        restore_payloads = {}
        for light_id in TARGET_LIGHT_IDS:
            current_state = get_light_state(light_id)
            if current_state:
                full_restore = {}
                for key in ["on", "dimming", "color", "color_temperature"]:
                    if key in current_state:
                        full_restore[key] = current_state[key]
                full_restore["dynamics"] = {"duration": 0} # snap back quickly
                
                was_on = current_state.get("on", {}).get("on", False)
                restore_payloads[light_id] = {
                    "was_on": was_on,
                    "full_restore": full_restore
                }
            else:
                logger.warning(f"Could not retrieve state for light {light_id}, will not flash it.")
                
        if not restore_payloads:
            logger.error("Could not retrieve state for any lights, aborting flash sequence.")
            return
                
        # To make it staccato, we need to instruct the bridge to change state instantly (transition=0)
        # 2. Flash on, off, on, off with short delays
        for state in [True, False, True, False]:
            for light_id, state_info in restore_payloads.items():
                payload = {"on": {"on": state}, "dynamics": {"duration": 0}}
                if state and "dimming" in state_info["full_restore"]:
                    # Explicitly set brightness to 100% so it visibly flashes even if it was previously off or dim
                    payload["dimming"] = {"brightness": 100.0}
                set_light_state(light_id, payload)
            # Use 0.4s to ensure bulbs have enough time to turn on and be visible from an off state
            time.sleep(0.4)
            
        # 3. Restore initial state
        logger.info("Restoring initial state...")
        off_lights_to_restore = []
        for light_id, state_info in restore_payloads.items():
            if state_info["was_on"]:
                set_light_state(light_id, state_info["full_restore"])
            else:
                # To restore the memory of an off light without causing an API error,
                # we must power it on with the previous parameters, then turn it off again.
                has_memory_params = any(k in state_info["full_restore"] for k in ["dimming", "color", "color_temperature"])
                if has_memory_params:
                    mem_restore = dict(state_info["full_restore"])
                    mem_restore["on"] = {"on": True}
                    set_light_state(light_id, mem_restore)
                    off_lights_to_restore.append(light_id)
                else:
                    set_light_state(light_id, {"on": {"on": False}, "dynamics": {"duration": 0}})
                
        if off_lights_to_restore:
            time.sleep(0.3)
            for light_id in off_lights_to_restore:
                set_light_state(light_id, {"on": {"on": False}, "dynamics": {"duration": 0}})
                
        logger.info("Flash sequence complete.")
        
    finally:
        # Prevent rapid re-triggering just in case
        time.sleep(2)
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
