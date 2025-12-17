/*
Version: 1.0

The script uses a motion sensor and a button to control the light.
A button push will toggle the light.
A long push on the button will turn off the light.

Hardware configuration for Shelly 2pm Gen3
Input 0 & 1: Detached
Input 0: Input Mode: Button
Input 1: Input Mode: Switch. Connect the PIR signal to Input 1

*/

// --- Configuration ---
let CONFIG = {
  PIR_OFF_DELAY_S: 10,  // Delay in seconds before turning off light after PIR motion stops
  s1_input_id: 0,       // Input ID for S1
  pir_input_id: 1,      // Input ID for S2 (PIR)
  output_id: 0          // Output ID for O1 (Light)
};

// --- Global state variables ---
let manualOverride = false;
let pirState = false;
let pirOffTimerHandle = null;

// Helper function to control the output Light (O1)
function setLight(state) {
  Shelly.call("Switch.Set", {
    id: CONFIG.output_id,
    on: state
  });
  print("Setting Light O1 to:", state ? "On" : "Off");
}

// Helper function to clear the "turn-off" timer
function clearPirTimer() {
  if (pirOffTimerHandle) {
    Timer.clear(pirOffTimerHandle);
    pirOffTimerHandle = null;
    print("PIR turn-off timer cleared.");
  }
}

// Event Handler for all Input changes
Shelly.addEventHandler(function (event) {
  if (event.name === "input") {
    clearPirTimer()
    // Handle S1 (Toggle Switch) Events
    if (event.id === CONFIG.s1_input_id) {
      if (event.info.event === "btn_down") {
        manualOverride = !manualOverride; // Toggle manual state
        print("Input S1 Down. Manual Switched light to:", manualOverride);
        setLight(manualOverride);
        return
      }
      if (event.info.event === "long_push") {
        manualOverride = false
        print("Input S1 Long Push. Manual Switched light to:", manualOverride);
        setLight(false);
      }
    }

    // Handle S2 (PIR) Events
    if (event.id === CONFIG.pir_input_id) {
      if (manualOverride === true) {
        print("PIR ignored as light turned on manually");
        return
      }
      pirState = event.info.state;
      print("PIR State changed to:", pirState ? "Motion" : "No Motion");
      if (pirState) {
        setLight(true);
      } else {
        pirOffTimerHandle = Timer.set(CONFIG.PIR_OFF_DELAY_S * 1000, false, function () {
          print("PIR timer expired.");
          pirOffTimerHandle = null;
          if (manualOverride === false) {
            setLight(false);
          }
        });
      } // end if pirState
    } // end if CONFIG.pir_input_id
  } // end if event.name === "input"

});

Shelly.addStatusHandler(function (e) {
  if (e.name === "switch" && e.id === CONFIG.output_id && e.delta.source === "WS_in") {
    manualOverride = e.delta.output
    print("Switch changed to", manualOverride ? "On." : "Off.", " Triggered source:", e.delta.source);
  }
});

// Main
// Wait 1 second after script starts to sync, ensuring inputs are ready
Timer.set(1000, false, function () {
  Shelly.call("Input.GetStatus", { id: CONFIG.pir_input_id }, function (res2) {
    if (res2 && res2.state !== undefined) {
      pirState = res2.state;
    }
    print("Initial Sync Complete: Manual Switch:", manualOverride, "PIR:", pirState);
  });
});
