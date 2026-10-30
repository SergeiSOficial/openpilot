# Android simulation port

The `android-fold3-port` branch builds installable, debug-signed APKs for `x86_64`
and `arm64-v8a`. The native dashboard runs the real driving model, planning,
control, vehicle interface, radar, selfdrive state, calibration, location,
parameter, delay, torque and driver-monitoring state daemons in private Android
service processes. The acceptance fixture contains 60 synchronized
road-camera pairs. Its final model result is drained through planning and control.

Camera capture, hardware acceleration, sustained real-time operation,
the original raylib UI and live vehicle transport are subsequent milestones. This APK
has no live panda worker or camera permission. The separate USB preflight screen
is read-only; `sendcan` remains an internal simulation output. Only the existing CAN wire-format conversion helpers
from `pandad` are packaged. The copied vehicle-interface and USB work remains in
the worktree.

## Toolchain

The 2026-10-28 acceptance runs completed 60 model frames, 60 plans,
251 control messages and 170 simulated CAN messages in 104.5 seconds on the
API 36 emulator and 24.7 seconds on the physical SM-F926B (Android 15, API 35).
All 12 daemon comparisons passed using their existing exclusions and tolerances.
Each Android suite passed 12/12 tests, including three USB-preflight software
tests with no physical panda connected. The earlier 7/7 host-adapter results are
retained as baseline evidence; the landscape update used source inspection and
Android target validation. Generated reports,
logs, APK checksums and dashboard captures are indexed in
`artifacts/android/README.md`, with the physical-phone evidence under
`artifacts/android/fold3/README.md`. The phone remained closed. Cover-screen
rotation, worker preservation, reset, backgrounding, worker death and corrupted
assets passed; physical unfolding and hinge transitions were not tested.
Measured timing and the comparison with comma four/chestnut are in
[the performance report](android-performance.md).

| Component | Version |
|---|---|
| Java | 17 |
| Gradle / Android Gradle Plugin | 9.1.0 / 9.0.1 |
| Android compile / target / minimum SDK | 36 / 36 / 30 |
| NDK / CMake | 28.2.13676358 / 3.22.1 |
| Chaquopy / embedded Python | 17.2.0 / 3.12 |
| NumPy / pycapnp | 2.5.3 / 2.1.0 |
| acados source | `8af9b0ad180940ef611884574a0b27a43504311d` |

Runtime dependency versions come from this checkout's `uv.lock`. Android wheel
recipes are under `tools/android/recipes`, including NumPy, pycapnp, msgq,
rednose, cffi, setproctitle, zstandard and pycryptodome. This revision's CAN
parser/packer and coordinate transformations are Python implementations, so they
are staged from source. Pose/car filters and the longitudinal solver are generated
on Linux and compiled separately for each ABI. acados uses generic BLASFEO/HPIPM,
without OpenMP or qpOASES; this solver uses HPIPM.

The Linux SDK, wheel builder, Python environments, dependency sources and Gradle
mirror live under `~/.cache/openpilot-android` in Ubuntu 24.04. Set
`OPENPILOT_ANDROID_CACHE` to relocate them. Environment exports apply only to the
build process. The Windows SDK is selected by `ANDROID_HOME`. Gradle runs under
WSL Java 17; the Windows NDK/CMake build the packaged native libraries.

Official compatibility and runtime restrictions:
[Chaquopy versions](https://chaquo.com/chaquopy/doc/current/versions.html),
[Android runtime restrictions](https://chaquo.com/chaquopy/doc/current/android.html#multiprocessing).

## Build and test

Run from this worktree in PowerShell. Prerequisites are Windows Python 3.12,
WSL Ubuntu 24.04, Git with initialized submodules/model assets, and an Android SDK
with command-line tools, API 36, build tools 36.0.0, NDK 28.2, CMake 3.22.1 and
the API 36 Google APIs x86-64 emulator image.

The latest host-test policy on 2026-10-28 permits reviewed Python checks and
established trusted runners. Previously flagged native helpers and similar ad hoc
binaries remain disabled, including shared-library/FFI/JIT substitutes. The full
`build-simulation.ps1` pipeline invokes native generation and inference helpers;
review its dependencies against that restriction before considering it. This UI
and USB-preflight work uses standard-library metadata checks and Android target
tests. No quarantined files may be restored or run.

For a dashboard-only change, reuse the validated model, fixture and target
libraries already staged in this worktree. The bundle validator reads hashes and
ELF metadata using Python's standard library; it does not load native libraries.
Build the Java UI and validate on Android:

```powershell
wsl -d Ubuntu-24.04 -- bash tools/android/build-wsl.sh -PwithModel -PprebuiltNative --offline :app:assembleDebug :app:assembleDebugAndroidTest
.\tools\android\create-emulator.ps1 -Launch
.\tools\android\test-emulator.ps1
.\tools\android\test-phone.ps1 -Serial <Fold3-serial>
```

Source/model/reference mismatch, missing kernel exports and target numerical
failure remain fatal. A computational change that makes the retained reference or
certificate stale requires an allowed target validation workflow; do not bypass
the gate or invoke the prohibited host pipeline.
`build-wsl.sh` mirrors inputs to a fixed Linux cache directory for build speed,
then copies APK outputs back to the worktree.

The dedicated AVD is `Openpilot_Fold3_API36`, with 6 GB RAM, four cores and console
port 5556. It retains the earlier AVD separately. It models a generic foldable,
with a 1768×2208 inner display and a narrower folded region, rather than Samsung's
complete hardware. `test-emulator.ps1` drives the emulator's actual `fold` and
`unfold` console commands and coordinates them with the instrumentation test.
The test checks window resizing, rotation, worker identity and completed replay.
This API 36 image exposes `CLOSED=1` while its legacy folded-state resource names
state 0. Its hinge event therefore does not automatically crop the window. The
test additionally applies the configured folded viewport with `wm size`, records
this workaround in `lifecycle.json`, and restores the previous viewport afterward.
It verifies both the hinge transition and a real window-size change.

Useful focused tests:

```powershell
.\tools\android\test-emulator.ps1 -TestClass ai.comma.openpilot.sim.ModelTest
.\tools\android\test-emulator.ps1 -TestClass ai.comma.openpilot.sim.RuntimeTest
.\tools\android\test-emulator.ps1 -TestClass ai.comma.openpilot.sim.ReplayTest
.\tools\android\test-emulator.ps1 -TestClass ai.comma.openpilot.sim.LifecycleTest
wsl -d Ubuntu-24.04 -- bash tools/android/host-python.sh -m unittest discover -s tools/android/tests -v
```

The test script parses JUnit results: Android's `am instrument` can return zero
even when tests fail. Every full replay has a 30-minute monotonic limit.

## Runtime and verification

Chaquopy starts one interpreter per service process. An internal Binder supervisor
starts only the approved daemon set, propagates the replay environment explicitly,
reports worker failure and tears down child bindings. Python multiprocessing and
executable launching are absent from the Android replay path. FIFO event polling
uses bounded monotonic waits, including health checks during slow inference.
Worker death stops the session; deliberate backgrounding terminates all workers.
Reset waits for termination and removes the previous session before rebinding.

Parameters, queues, event FIFOs, VisionIPC buffers, caches and logs use
`files/s/<session>`. Shared model/schema files are checksum verified and installed
atomically. Both schema loaders use the same physical directory to preserve
Cap'n Proto type identity. Android patches are applied to staging directories;
the submodule checkouts remain unchanged.

The standard model is `driving_supercombo.onnx`, SHA-256
`65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce`.
tinygrad dispatches captured C kernels from `libopenpilot_kernels.so`; an unknown
kernel fails immediately. No on-device compiler is invoked. Host and Android
kernels use `-O2 -ffreestanding -fno-math-errno -ffp-contract=off`. Models, source
hashes, compiler information and kernel manifests accompany the build artifacts.

The fixture is route `98395b7c5b27882e|0000002b--2686b5a2d0`, segment 1.
`fixture.sources.json` pins all public source URLs and checksums. Host preparation
selects encoded frame IDs 1–60, decodes canonical NV12, retains initialization
messages and records stride/padding settings and per-buffer hashes. The maximum
timestamp difference between camera pairs is 17,135 ns. Android verifies buffers
before inference. Recorded intermediate outputs are excluded when their producing
daemon runs; newly computed messages are routed by the existing replay scheduler.

The car worker receives current-source CarParams reconstructed from the fixture's
CAN and firmware records before timeline replay. It then runs the original `Car`
class and real vehicle/radar interfaces. This avoids the live fingerprint startup
loop consuming a wall-clock-dependent number of timeline CAN packets.

Both reference and Android restore the first recorded calibration, vehicle and
torque parameter state. Before the first camera pair, the model's replay adapter
waits for its VisionIPC receive and seeds the recorded device, narrow-camera and
extrinsics snapshots. Computed calibration then replaces the startup snapshot on
the normal timeline. This prevents inference from starting with a singular camera
transform. Android rejects non-finite or singular transforms before warping;
zero transforms previously exposed architecture-dependent NaN-to-integer behavior
in the generated warp code.

Reference and Android outputs are compared per service, preserving emission order,
using the existing `ProcessConfig.ignore` fields and tolerances. The computational
source hash covers uncommitted port code as well as source revisions, native
integration and captured kernels. The APK rejects a reference from another source,
model or fixture. `verification.json` includes the per-daemon comparison results.
The Android parser rounds scalar binary64 exponentials to float32 so probability
messages forwarded to radar remain reproducible across NumPy CPU implementations.
The existing radar comparison remains strict; its tolerance has not changed.

For a connected Fold 3, leave the phone unlocked and closed with USB debugging
authorized, then select its serial explicitly:

```powershell
.\tools\android\test-phone.ps1 -Serial <Fold3-serial>
adb -s <Fold3-serial> shell run-as ai.comma.openpilot.sim cat files/last-lifecycle-session.txt
py -3.12 tools/android/collect_emulator.py --physical --serial <Fold3-serial> --session <session-id>
py -3.12 tools/android/package_phone.py --session <session-id>
```

This script installs the ARM64 APK and tests the real cover screen. It never sends
emulator console commands, forces hinge state or changes display-size overrides.
Rotation uses this app's requested orientation and restores it afterwards. The
physical test records hinge transitions as untested. Emulator fold/unfold testing
remains a separate test on its dedicated AVD.

The dashboard exposes Start, Stop, Reset, camera playback, a perspective preview
of the model path, actuator values, worker health and progress. Its path projection
uses a nominal camera height. Export saves the local JSON verification report
through Android's document picker.

Landscape is the default orientation (`sensorLandscape`). The camera fills the
left pane; a scrollable status pane and fixed Start/Stop/Reset/Export controls sit
on the right. The layout adapts in place to portrait or resized windows, preserving
the current frame and worker processes. Android 16 may override orientation requests
on large displays, so the portrait arrangement remains supported
([Android orientation behavior](https://developer.android.com/develop/adaptive-apps/guides/app-orientation-aspect-ratio-resizability)).
The folded-phone test checks default landscape, all four controls fully visible
with single-line labels, a temporary portrait fallback and a return to landscape
during the same verified 60-frame simulation.

The **Red panda** toolbar button opens the Android USB-host preflight and passive
CAN monitor for the target 2018 Ioniq PHEV. This is separate from replay and cannot
transmit CAN, flash firmware or enable vehicle control. No red panda is connected
yet; physical USB/CAN and vehicle control remain unverified. See
[the red panda integration status and connection steps](android-red-panda.md).

## Outputs

APKs: `android/app/build/outputs/apk/debug/app-{x86_64,arm64-v8a}-debug.apk`.
The universal debug APK and instrumentation APK are also generated.

```powershell
py -3.12 tools/android/collect_emulator.py
# Select the completed fold-test session when collecting its captures:
py -3.12 tools/android/collect_emulator.py --session <16-character-session-id>
py -3.12 tools/android/package_delivery.py --session <completed-fold-session-id>
```

Evidence is saved under `artifacts/android/<session>`: verification and numerical
comparison JSON, computed Cap'n Proto messages, Logcat, lifecycle results and
dashboard captures. Build/test logs and the host numerical certificate remain
under `tools/android/.cache`. ARM64 compilation is reported separately from
physical-phone acceptance.
