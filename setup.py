import requests
import urllib3
import time
import sys
import json

# Disable the warning about the Hue Bridge's self-signed certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def discover_bridge():
    print("Searching for Hue Bridge on network...")
    try:
        response = requests.get("https://discovery.meethue.com/")
        devices = response.json()
        if not devices:
            print("Could not find a Hue bridge automatically. If you know the IP, you can enter it manually.")
            ip = input("Enter Hue Bridge IP: ").strip()
            return ip
        else:
            ip = devices[0]['internalipaddress']
            print(f"Found Hue Bridge at {ip}")
            return ip
    except Exception as e:
        print(f"Error discovering bridge: {e}")
        ip = input("Enter Hue Bridge IP: ").strip()
        return ip

def get_app_key(ip):
    print("\n" + "="*50)
    print("PRESS THE LINK BUTTON ON YOUR HUE BRIDGE NOW!")
    print("="*50 + "\n")
    
    url = f"http://{ip}/api"
    payload = {"devicetype": "hue_reactor#app"}
    
    for i in range(30):
        try:
            r = requests.post(url, json=payload, timeout=5)
            r_json = r.json()
            if isinstance(r_json, list) and 'error' in r_json[0]:
                if r_json[0]['error']['type'] == 101: # Link button not pressed
                    print(f"Waiting for link button press... ({30-i} seconds left)")
                    time.sleep(1)
                    continue
            elif isinstance(r_json, list) and 'success' in r_json[0]:
                username = r_json[0]['success']['username']
                print(f"\nSUCCESS! Your API Key (Username) is: {username}")
                return username
        except Exception as e:
            print(f"Error connecting to bridge: {e}")
            break
            
    print("\nFailed to get API key. Did you press the link button on the bridge?")
    return None

def fetch_devices(ip, app_key):
    headers = {"hue-application-key": app_key}
    
    print("\nFetching Lights...")
    try:
        r = requests.get(f"https://{ip}/clip/v2/resource/light", headers=headers, verify=False)
        r.raise_for_status()
        lights = r.json().get('data', [])
        for light in lights:
            name = light.get('metadata', {}).get('name', 'Unknown')
            light_id = light.get('id')
            print(f" - {name}: {light_id}")
    except Exception as e:
        print(f"Error fetching lights: {e}")
        
    print("\nFetching Motion Sensors...")
    try:
        r = requests.get(f"https://{ip}/clip/v2/resource/device", headers=headers, verify=False)
        r.raise_for_status()
        devices = r.json().get('data', [])
        
        for d in devices:
            # We look for devices that have a 'services' list containing instances of type 'motion'
            services = d.get('services', [])
            has_motion = any(s.get('rtype') == 'motion' for s in services)
            
            if has_motion:
                name = d.get('metadata', {}).get('name', 'Unknown')
                # Now we need the actual motion service ID, not just the device ID, because SSE events 
                # often report the service ID for the motion event.
                motion_service_id = next(s.get('rid') for s in services if s.get('rtype') == 'motion')
                print(f" - {name} (Device ID: {d.get('id')}) -> Motion Service ID: {motion_service_id}")
    except Exception as e:
        print(f"Error fetching devices/sensors: {e}")


def main():
    print("Welcome to Hue Reactor Setup\n")
    ip = discover_bridge()
    if not ip:
        print("Could not proceed without Bridge IP.")
        sys.exit(1)
        
    app_key = get_app_key(ip)
    if not app_key:
        sys.exit(1)
        
    print("\n" + "*"*60)
    print("Please save the following values for your .env file:")
    print(f"HUE_BRIDGE_IP={ip}")
    print(f"HUE_APP_KEY={app_key}")
    print("*"*60 + "\n")
    
    fetch_devices(ip, app_key)
    
if __name__ == "__main__":
    main()
