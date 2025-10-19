"""
<plugin key="BMWviaMQTT" name="BMW via MQTT" author="sincze" version="2.0.3" externallink="https://github.com/FilipDem/Domoticz-BMW-plugin">
    <params>
        <param field="Address" label="MQTT Server" width="200px" required="true" default="localhost"/>
        <param field="Port" label="Port" width="75px" required="true" default="1883"/>
        <param field="Username" label="Username" width="150px"/>
        <param field="Password" label="Password" width="150px" password="true"/>
        <param field="Mode1" label="MQTT Topic Root" width="150px" default="bmw/"/>
        <param field="Mode2" label="VIN" width="200px" required="true" default="WBY31AW040FP12345"/>
    </params>
</plugin>
"""

import Domoticz
import json
import paho.mqtt.client as mqtt

# --- Device definitions ---
DEVICE_MAPPINGS = {
    "Mileage": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
    "RemainingRangeTotal": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
    "RemainingRangeElec": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
    "LastRemainingRange": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
    "BatteryLevel": {"Type": 243, "Subtype": 6},
    "ChargingTime": {"TypeName": "Custom", "Options": {"Custom": "1;min"}},
    "Locked": {"TypeName": "Switch"},
    "Charging": {"TypeName": "Switch"},
    "Driving": {"TypeName": "Switch"},
    "Doors": {"TypeName": "Switch"},
    "Windows": {"TypeName": "Switch"},
    "Location": {"TypeName": "Text"},
}

# --- Datapoint mappings ---
DATAPOINT_MAPPING = {
    "vehicle.vehicle.travelledDistance": "Mileage",
    "vehicle.drivetrain.totalRemainingRange": "RemainingRangeTotal",
    "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange": "RemainingRangeElec",
    "vehicle.drivetrain.lastRemainingRange": "LastRemainingRange",
    "vehicle.drivetrain.batteryManagement.header": "BatteryLevel",
    "vehicle.drivetrain.electricEngine.charging.timeRemaining": "ChargingTime",
    "vehicle.cabin.door.status": "Locked",
    "vehicle.drivetrain.electricEngine.charging.hvStatus": "Charging",
    "vehicle.isMoving": "Driving",
    # Arrays
    "vehicle.cabin.door.row1.driver.isOpen": "Doors",
    "vehicle.cabin.door.row1.passenger.isOpen": "Doors",
    "vehicle.cabin.door.row2.driver.isOpen": "Doors",
    "vehicle.cabin.door.row2.passenger.isOpen": "Doors",
    "vehicle.body.trunk.door.isOpen": "Doors",
    "vehicle.cabin.window.row1.driver.status": "Windows",
    "vehicle.cabin.window.row1.passenger.status": "Windows",
    "vehicle.cabin.window.row2.driver.status": "Windows",
    "vehicle.cabin.window.row2.passenger.status": "Windows",
    "vehicle.cabin.sunroof.overallStatus": "Windows",
    "vehicle.cabin.infotainment.navigation.currentLocation.latitude": "Location",
    "vehicle.cabin.infotainment.navigation.currentLocation.longitude": "Location",
}

# --- Assign fixed unit numbers ---
DEVICE_UNITS = {name: idx + 1 for idx, name in enumerate(DEVICE_MAPPINGS.keys())}

# --- Plugin class ---
class BasePlugin:
    mqttClient = None

    def onStart(self):
        self.topicRoot = Parameters["Mode1"]
        self.vin = Parameters["Mode2"]
        Domoticz.Log(f"Starting BMW MQTT plugin for VIN {self.vin}")

        # MQTT setup
        self.mqttClient = mqtt.Client()
        if Parameters["Username"]:
            self.mqttClient.username_pw_set(Parameters["Username"], Parameters["Password"])
        self.mqttClient.on_connect = self.on_connect
        self.mqttClient.on_message = self.on_message
        self.mqttClient.connect(Parameters["Address"], int(Parameters["Port"]), 60)
        self.mqttClient.loop_start()

        self.create_devices()

    def onStop(self):
        Domoticz.Log("BMW MQTT plugin stopped")
        if self.mqttClient:
            self.mqttClient.loop_stop()
            self.mqttClient.disconnect()

    def on_connect(self, client, userdata, flags, rc):
        topic = f"{self.topicRoot}{self.vin}/#"
        client.subscribe(topic)
        Domoticz.Log(f"Connected to MQTT broker (rc={rc}), subscribed to {topic}")

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            Domoticz.Error(f"MQTT JSON decode failed: {e}")
            return

        if data.get("vin") != self.vin:
            return

        datapoints = data.get("data", {})
        array_cache = {"Doors": [], "Windows": [], "Location": []}

        for dp, val_obj in datapoints.items():
            val = val_obj.get("value")
            if dp in DATAPOINT_MAPPING:
                name = DATAPOINT_MAPPING[dp]

                # Aggregate arrays
                if name in array_cache:
                    array_cache[name].append(val)
                else:
                    self.update_single_device(name, val)

        # Update aggregated devices
        for name, values in array_cache.items():
            if values:
                if name in ["Doors", "Windows"]:
                    val = 1 if any(v in ["true", "open", True] for v in values) else 0
                    sVal = "On" if val else "Off"
                elif name == "Location":
                    val = f"{values[0]},{values[1]}" if len(values) >= 2 else "Unknown"
                    sVal = val
                else:
                    continue
                self.update_single_device(name, val, sVal)

    # --- Device creation ---
    def create_devices(self):
        Domoticz.Log("Checking/creating Domoticz devices...")
        for name, device_info in DEVICE_MAPPINGS.items():
            unit = DEVICE_UNITS[name]
            if unit not in Devices:
                Domoticz.Device(Name=name, Unit=unit, **device_info).Create()
                Domoticz.Log(f"Created device {unit}: {name}")
        Domoticz.Log("Device initialization complete.")

    # --- Single device update ---
    def update_single_device(self, name, value, sValue=None):
        unit = DEVICE_UNITS.get(name)
        if not unit or unit not in Devices:
            Domoticz.Error(f"Device {name} not found for update")
            return

        device = Devices[unit]

        if sValue is None:
            if name in ["Locked", "Doors", "Windows", "Charging", "Driving"]:
                val = bool(value) if not isinstance(value, str) else value.lower() in ["true", "open", "on", "charging", "locked"]
                nValue = 1 if val else 0
                sValue = "On" if val else "Off"
            elif name == "BatteryLevel":
                try:
                    sValue = str(int(value))
                    nValue = int(value)
                except:
                    sValue = str(value)
                    nValue = 0
            elif name in ["Mileage", "RemainingRangeTotal", "RemainingRangeElec", "ChargingTime", "LastRemainingRange"]:
                try:
                    sValue = f"{float(value):.0f}"
                    nValue = int(float(value))
                except:
                    sValue = str(value)
                    nValue = 0
            else:
                sValue = str(value)
                nValue = 0
        else:
            nValue = 1 if sValue == "On" else 0 if name in ["Doors","Windows","Locked","Charging","Driving"] else 0

        device.Update(nValue=nValue, sValue=str(sValue))
        Domoticz.Log(f"Updated {name} = {sValue}")


# --- Domoticz plugin callbacks ---
global _plugin
_plugin = BasePlugin()

def onStart(): _plugin.onStart()
def onStop(): _plugin.onStop()
def onMessage(Data): pass
