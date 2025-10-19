"""
<plugin key="BMWviaMQTT" name="BMW via MQTT" author="sincze" version="2.0.0" externallink="https://github.com/FilipDem/Domoticz-BMW-plugin">
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

# --- Mappings from original plugin ---
BMW_MAPPING_TEMPLATE = {
    "Mileage": "vehicle.vehicle.travelledDistance",
    "Doors": [
        "vehicle.cabin.door.row1.driver.isOpen",
        "vehicle.cabin.door.row1.passenger.isOpen",
        "vehicle.cabin.door.row2.driver.isOpen",
        "vehicle.cabin.door.row2.passenger.isOpen",
        "vehicle.body.trunk.door.isOpen"
    ],
    "Windows": [
        "vehicle.cabin.window.row1.driver.status",
        "vehicle.cabin.window.row1.passenger.status",
        "vehicle.cabin.window.row2.driver.status",
        "vehicle.cabin.window.row2.passenger.status",
        "vehicle.cabin.sunroof.overallStatus"
    ],
    "Locked": "vehicle.cabin.door.status",
    "Location": [
        "vehicle.cabin.infotainment.navigation.currentLocation.latitude",
        "vehicle.cabin.infotainment.navigation.currentLocation.longitude"
    ],
    "Driving": "vehicle.isMoving",
    "RemainingRangeTotal": "vehicle.drivetrain.totalRemainingRange",
    "RemainingRangeElec": "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange",
    "Charging": "vehicle.drivetrain.electricEngine.charging.hvStatus",
    "BatteryLevel": "vehicle.drivetrain.batteryManagement.header",
    "ChargingTime": "vehicle.drivetrain.electricEngine.charging.timeRemaining"
}


# --- Main Plugin Class ---
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

        # Create Domoticz devices like original plugin
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
            return  # Ignore other VINs

        datapoints = data.get("data", {})
        for datapoint, value_obj in datapoints.items():
            val = value_obj.get("value")
            self.update_devices(datapoint, val)

    # --- Device creation section ---
    def create_devices(self):
        Domoticz.Log("Checking/creating Domoticz devices...")
        idx = 1

        device_map = {
            "Mileage": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
            "RemainingRangeTotal": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
            "RemainingRangeElec": {"TypeName": "Custom", "Options": {"Custom": "1;km"}},
            "BatteryLevel": {"Type": 243, "Subtype": 6},  # Battery Percentage
            "ChargingTime": {"TypeName": "Custom", "Options": {"Custom": "1;min"}},
            "Locked": {"TypeName": "Switch"},
            "Charging": {"TypeName": "Switch"},
            "Driving": {"TypeName": "Switch"},
            "Doors": {"TypeName": "Switch"},
            "Windows": {"TypeName": "Switch"},
            "Location": {"TypeName": "Text"}
        }

        for key in BMW_MAPPING_TEMPLATE.keys():
            if idx not in Devices:
                dev_type = device_map.get(key, {"TypeName": "Text"})
                Domoticz.Device(Name=key, Unit=idx, **dev_type).Create()
                Domoticz.Log(f"Created device {idx}: {key}")
            idx += 1
        Domoticz.Log("Device initialization complete.")

    # --- Processing MQTT updates ---
    def update_devices(self, datapoint, value):
        """Find which Domoticz device should be updated based on the datapoint name."""
        for name, keys in BMW_MAPPING_TEMPLATE.items():
            if isinstance(keys, list):
                if datapoint in keys:
                    self.update_device(name, value)
                    return
            elif datapoint == keys:
                self.update_device(name, value)
                return

    def update_device(self, name, value):
        """Update the correct Domoticz device according to type logic."""
        for unit, device in Devices.items():
            if device.Name != name:
                continue

            nValue, sValue = 0, str(value)

            # Custom behavior like original plugin
            if name in ["Locked", "Doors", "Windows", "Charging", "Driving"]:
                # Boolean-like conversion
                if isinstance(value, str):
                    val = value.lower() in ["true", "open", "on", "charging"]
                else:
                    val = bool(value)
                nValue = 1 if val else 0
                sValue = "On" if val else "Off"

            elif name == "BatteryLevel":
                try:
                    sValue = str(int(value))
                    nValue = int(value)
                except Exception:
                    pass

            elif name in ["Mileage", "RemainingRangeTotal", "RemainingRangeElec", "ChargingTime"]:
                try:
                    sValue = f"{float(value):.0f}"
                except Exception:
                    sValue = str(value)

            # Update Domoticz
            device.Update(nValue=nValue, sValue=sValue)
            Domoticz.Log(f"Updated {name}: {sValue}")
            return

        Domoticz.Error(f"Received datapoint for {name} but no matching device found.")


# --- Domoticz plugin callbacks ---
global _plugin
_plugin = BasePlugin()

def onStart(): _plugin.onStart()
def onStop(): _plugin.onStop()
def onMessage(Data): pass
