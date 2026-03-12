# Hue Reactor

## How it Works

The application connects to the Hue Bridge Event Stream (SSE endpoint) to listen for motion events from a specific sensor. When motion is detected, it triggers a sequence to flash one or more target lights for a couple of seconds using the native Hue "signaling" feature. This ensures that lights gracefully return to their previous states (e.g., if they were originally off, they will turn back off), avoiding disruptive changes.

## Setup

To set up the application, you need to find your Hue Bridge IP, generate an Application Key, and identify the IDs of your motion sensors and target lights. The provided setup script will help you do all of this.

Run the setup script:
```bash
python setup.py
```

The script will:
1. Discover your Hue Bridge automatically on the network (or prompt you to enter the IP manually).
2. Instruct you to **press the link button** on your Hue Bridge.
3. Generate and display the values for `HUE_BRIDGE_IP` and `HUE_APP_KEY`.
4. Fetch and list the names and IDs for all your connected lights and motion sensors. Note: For motion sensors, you will need the **Motion Service ID**, which is specifically provided by the script.

Create a `.env` file in the root directory of the project and add the values provided by the setup script:
```env
HUE_BRIDGE_IP=your_bridge_ip
HUE_APP_KEY=your_app_key
TARGET_SENSOR_ID=your_motion_sensor_service_id
TARGET_LIGHT_IDS=light_id_1,light_id_2
```
*Note: You can specify multiple `TARGET_LIGHT_IDS` by separating them with commas.*

## Deployment

You can easily deploy the application using Docker Compose. The included `docker-compose.yml` is configured to pull the pre-built image from the GitHub Container Registry.

To start the application in the background, run:
```bash
docker compose up -d
```

The container (`hue_reactor`) will automatically load the environment variables from your `.env` file and is configured to restart automatically unless stopped.
