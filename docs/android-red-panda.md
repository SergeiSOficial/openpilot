# Fold 3, red panda and 2018 Ioniq PHEV

Checkpoint: 2026-10-28, with the panda not yet connected.

**Vehicle control is not qualified or enabled in this APK.** The target is the
user's Hyundai Ioniq PHEV 2018. No red panda is currently connected, and no CAN
traffic from that car has been captured. The phone's measured model cycle is
246–250 ms against a 50 ms budget; live road-camera and driver-monitoring inference
are also incomplete. See [performance](android-performance.md).

## Implemented Android preflight

The landscape dashboard has a **Red panda** button. It opens a separate screen for
USB host permission, hardware/protocol/health checks and passive CAN reception:

- Uses Android `UsbManager`/`UsbDeviceConnection`, without root or host libusb.
- Accepts application-mode VID/PID `3801:ddcc` or `bbaa:ddcc`, then verifies hardware
  type `7` and interface 0's bulk endpoints `0x81`/`0x03`.
- Pins the current checkout's 32-bit health and CAN protocol hashes. These are
  SHA-256-derived hashes, not the old one-byte packet version numbers.
- Parses the packed 48-byte health layout generated from the pinned source.
- Accepts CAN only while the panda reports `silent` or `noOutput` and controls
  disallowed. An existing active safety session causes disconnect rather than
  changing another controller's configuration.
- Validates CAN/CAN-FD DLC, bus, checksum and fragmented USB reads. Idle reads are
  bounded and cancelled; errors, detach and backgrounding close the connection.
- Drains CAN independently from the slower UI/status refresh interval.
- Reports bus counts and health in the app, with the latest status in app-private
  `files/panda/latest.json`.

The Android USB adapter exposes only vendor **IN** requests `c1`, `dd`, `d2` and
bulk **IN** `81`. It has no CAN OUT, safety-mode write, heartbeat-disable, firmware
flash or engagement action. Recorded replay `sendcan` is isolated from USB.
The copied desktop pandad USB implementation is retained but is not the Android
transport; its automatic firmware preparation is not invoked by this screen.

This is a preflight/RX implementation, not a live `pandad`/`sendcan` bridge. USB
enumeration or matching protocol hashes alone cannot establish car-control readiness.
Full firmware-signature validation, physical RX/TX and vehicle safety behavior are
still unverified. The application reports `actuation_allowed=false` explicitly.

## Vehicle-specific limits

The repository's **2019 PHEV** profile is a candidate for the 2018 car, not a
confirmed match. Do not force that fingerprint or use the 2020–22 profile.
Retain the candidate's Hyundai C harness requirement (subject to actual connector
and pinout verification), HYBRID safety flag, torque limits and **32 mph / 51.5 km/h
minimum steering speed**. With stock SCC, the candidate uses `hyundai` safety with
`HYBRID_GAS`, without `LONG`, and factory ACC retains longitudinal ownership.
See [the existing car verification notes](how-to/ioniq-phev-2018.md).

## Next physical steps

1. Start with the panda on an isolated bench. Install this APK, disconnect the
   phone's PC USB cable and attach the panda through USB OTG or a suitable powered
   hub. The phone must be the USB host. Simultaneous ADB inspection requires an
   independently authorized wireless-debugging connection; this implementation
   does not change Android debugging or USB security settings.
2. Open **Red panda → Connect / monitor** and grant Android's USB permission.
   Verify hardware identity, protocol versions, passive safety state, disconnect
   behavior and health. An incompatible firmware is reported, never auto-flashed.
3. Capture real CAN and ECU firmware identification from the stationary target
   vehicle with the verified harness. Review the exact model/market identification
   before selecting any car safety configuration.
4. Implement and validate the remaining live camera/model/control path, bounded
   command freshness and heartbeat supervision. Meet the model and control timing
   deadlines before enabling a vehicle-specific transmit bridge. Never republish
   fixture commands into a car.
5. Validate physical CAN TX, checksum/counter behavior, vehicle safety rejection,
   driver override, worker death, USB loss and stale-control shutdown on a bench/HIL
   setup, then perform the appropriate supervised vehicle acceptance stage.

The absent-device UI and fake transport tests do not satisfy these physical steps.
The final checkpoint passed **12/12 Android tests on the physical Fold 3 and
12/12 on the emulator**. The Fold 3 advertises USB-host support, but no physical
Panda transfers, CAN RX/TX or vehicle actuation were tested. Machine-readable
evidence: [readiness report](../artifacts/android/fold3/panda/readiness.json).

## Reproduction and sources

`generate_panda_protocol.py` reads the pinned health/CAN headers and extracts only
the audited pure Python packer/checksum functions to generate wire goldens. It
does not import panda (which would load USB/FFI dependencies), invoke a compiler or
run a native host helper.

```powershell
py -3.12 tools/android/generate_panda_protocol.py
wsl -d Ubuntu-24.04 -- bash tools/android/build-wsl.sh -PwithModel -PprebuiltNative --offline :app:assembleDebug :app:assembleDebugAndroidTest
.\tools\android\test-phone.ps1 -Serial <Fold3-serial> -TestClass ai.comma.openpilot.sim.PandaUsbTest
```

The Android tests cover upstream wire goldens, partial frames, CRC corruption,
wrong hardware/protocol, short health, active safety/controls state and the
absent-device screen. They run on Android and do not replace USB or vehicle HIL.

References: [Android USB host API](https://developer.android.com/develop/connectivity/usb/host),
[panda safety model](https://github.com/commaai/panda#safety-model),
[pinned protocol metadata](../android/app/src/main/assets/panda/protocol.json).
