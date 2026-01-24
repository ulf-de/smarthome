/*
Version: 1.0

The script uses a Shelly BluMotion sensor to trigger the light.
The button will override the motion sensor.

Hardware configuration for Shelly Mini gen3
Input 0: Momentary press (button)

*/

// Configuration
const CONFIG = {
  lux_id: 200,
  motion_id: 201,
  lux_threshold: 35,
  off_delay: 70000, // 70 seconds in milliseconds
  on_delay: 600000, // 10 minutes in the case no off signal is received from the sensor
  relay_id: 0
};

let isManual = false;
let offTimer = null;
let onTimer = null;
let hasMotion = false;
let lastLux = 0;

// Monitor Lux and Motion updates
Shelly.addStatusHandler(function(event) {
  if (event.name === "switch" && event.id === CONFIG.relay_id) {
    if (event.delta.source === "WS_in" || event.delta.source === "button") {
      Timer.clear(offTimer);
      let sw = Shelly.getComponentStatus("switch:0");
      if (typeof sw === 'undefined') {
        print("Shelly.getComponentStatus was not ready, retry in 1s")
      }
      if (sw && sw.output === true) {
        isManual = true;
        print("Manual light ON by", event.delta.source);
      } else {
        isManual = false;
        print("Manual light OFF by", event.delta.source);
      }
    return
    }
  }

  // Update Lux value
  if (event.name === "bthomesensor" && event.id === CONFIG.lux_id) {
    if (typeof event.delta.value !== 'undefined') {
      // Check if switch:0 is OFF before updating lastLux
      let sw = Shelly.getComponentStatus("switch:0");
      if (sw && sw.output === false) {
        lastLux = event.delta.value;
        print("Detected new lux:", lastLux);
      } else {
        print("Current lux:", event.delta.value, "ignored (light is on), continue with old value:", lastLux);
      }
    }
  }

  // Handle Motion logic
  if (event.name === "bthomesensor" && event.id === CONFIG.motion_id) {
    hasMotion = event.delta.value;

    // If manual mode is active, ignore motion sensor completely
    if (isManual) {
      print("Light was activated manually. Ignoring motion:", hasMotion);
      return;
    }
 
    if (hasMotion && lastLux < CONFIG.lux_threshold) {
      // Turn light ON
      Timer.clear(onTimer);
      Timer.clear(offTimer);
      Shelly.call("Switch.Set", { id: CONFIG.relay_id, on: true });
      print("Motion detected and dark. Light ON.");
      onTimer = Timer.set(CONFIG.on_delay, false, function() {
        Shelly.call("Switch.Set", { id: CONFIG.relay_id, on: false });
        print("No off signal received after", CONFIG.on_delay, "ms. Light OFF.");
      });

    } 
    else if (!hasMotion && isManual === false) {
      // Start Off-Timer
      Timer.clear(onTimer);
      Timer.clear(offTimer);
      offTimer = Timer.set(CONFIG.off_delay, false, function() {
        Shelly.call("Switch.Set", { id: CONFIG.relay_id, on: false });
        print("No motion for", CONFIG.off_delay, "ms. Light OFF.");
      });
    }
  }
});
