# Fold3 live shadow diagnostic

This root-free ARM64 app is a stationary, disengaged bench integration. It never starts Panda, card, controls, planning or vehicle transport in Live Shadow or Cabin Diagnostic. Recorded simulation remains available and the existing `ai.comma.openpilot.sim` installation is separate from `com.samsung.android.openpilot.shadow`.

The [live stability update](android-live-stability.md) documents continuous IMU/GNSS publication, mounting profiles, sustained road-backend qualification, thermal handling and the current validation workflow. Road inference requires the sustained qualification certificate; an absent certificate leaves cameras and sensors running.

## Build and install

Requirements are the existing Android SDK/NDK 28.2.13676358, CMake 3.22.1, WSL Ubuntu 24.04 with the established Gradle/Chaquopy build cache, the retained model/fixture bundle, and the official ONNX Runtime Android 1.23.2 AAR in `tools/android/.cache/live-deps/`. The Maven artifact is `com.microsoft.onnxruntime:onnxruntime-android:1.23.2`. No host model compiler or generated native host helper is needed or permitted by this workflow.

From the repository directory in PowerShell:

```powershell
python -m unittest discover -s tools/android/tests -p test_live_policy.py -q
./tools/android/build-live.ps1
python tools/android/validate_live_bundle.py --check-source
adb -s RFCR81Y1TBJ install --no-incremental -r -g android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk
```

The native build compiles only Android ARM64 `libopenpilot_ipc.so`. `stage_live.py` copies the original driver ONNX and hashes the current live sources; it does not regenerate model code or relabel a historical certificate. The retained model, reference, fixture and packaged kernel hashes remain checked. Runtime numerical validation is mandatory before enabling a GPU model.

Select **Live Shadow**, **Cabin Diagnostic** or **GPU validation**, then Start. Recorded returns to the fixture dashboard. The user selected **right-hand drive** for this device; the seat selection is explicit and persists after Start. CLI runs also accept `--seat right`.

```powershell
python tools/android/test_live.py --serial RFCR81Y1TBJ --mode gpucheck --duration 5 --timeout 300
python tools/android/test_live.py --serial RFCR81Y1TBJ --mode live --seat right --duration 1200 --timeout 1500
python tools/android/test_live.py --serial RFCR81Y1TBJ --mode cabin --seat right --duration 1200 --timeout 1500
adb -s RFCR81Y1TBJ install --no-incremental -r android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s RFCR81Y1TBJ shell am instrument -w -r -e class ai.comma.openpilot.sim.LivePipelineTest com.samsung.android.openpilot.shadow.test/androidx.test.runner.AndroidJUnitRunner
adb -s RFCR81Y1TBJ shell am instrument -w -r -e class ai.comma.openpilot.sim.ReplayTest com.samsung.android.openpilot.shadow.test/androidx.test.runner.AndroidJUnitRunner
```

`test_live.py` requires the physical SM-F926B to remain folded. It does **not** run the diagnostic ADB camera preflight. Evidence is text JSON/JSONL plus bounded logcat in `artifacts/android/live/<session>/`. Permission grants in the install command are for this explicitly requested local test.

## Pipeline and validity

`LiveCameraService` owns the camera devices in `:camerad`. The verified rear recipe uses logical camera 20, Samsung initialization, a genuine display SurfaceView, YUV roles `1` and `0x101`, and a passive JPEG output. No JPEG is requested or saved. Standard physical-ID output bindings are deliberately omitted because this firmware supplies invalid physical metadata for them. Rear stream identity was previously confirmed by independent middle/bottom lens-cover checks; see [camera investigation](fold3-camera-investigation.md).

The cover camera is ID 1 at advertised 1280x720/30 fps. Earlier simultaneous front/rear attempts failed with camera error 4 and disturbed provider recovery. Normal rear launches now open only the verified rear pair. Cabin Diagnostic is separately selectable; the combined-camera retry is absent from the normal UI.

Each camera callback has a dedicated thread and `acquireLatestImage` with four ImageReader slots. JNI packs crop/row/pixel-stride-aware YUV directly into eight pooled aligned NV12 VisionIPC buffers per role. The single inference coordinator reads an owned native snapshot, rejects ring overwrite, and uploads directly to CL. There is no full-frame NumPy/Java pixel packing. Camera timestamps remain sensor timestamps normalized from BOOTTIME to MONOTONIC; readout-end metadata is explicitly unmeasured. Old, reused, future-clock and overly skewed pairs are rejected. The slower secondary stream makes road temporal predictions experimental.

`gpu.py` uses the app-visible `libOpenCL.so` dependency and tinygrad CL. Retained lowered kernels are rendered and compiled on Android; scalar `__fp16` arithmetic is adapted to the captured C semantics. Weights, tensor layout, recurrent state and strict `rtol=1e-4, atol=1e-5` stay unchanged. A failed numerical gate disables road predictions while preserving previews/capture. GPU recurrent state and preprocessing stay on device when that gate passes.

The driver CL candidate is independently checked against official ONNX Runtime CPU using the same original ONNX. Its failed comparison leaves it disabled. **Cabin Diagnostic explicitly uses GPU preprocessing plus the original ONNX through official CPU ORT**, with a native CL readback to a direct ByteBuffer. It is labeled `ORT_CPU_REFERENCE`; this is not a GPU-driver-model acceptance claim. The 1,382,400-pixel luma warp is compared against an independent pixel oracle. The persistent CPU session is warmed before timed live frames.

Road jobs have priority under one GPU owner; cabin work uses the latest fresh frame between road jobs. The app publishes the established VisionIPC streams, real model output packets and runs unmodified `dmonitoringd` as the only policy worker. Calibration and monitoring validity stay false until their gates are met. Missing/stale/uncertain input never becomes an attentive result. Model face/eye/blink/head-pose values are diagnostic outputs, and policy output is shown with its validity.

All phone profiles are Android-specific and provisional: invalid factory principal points are rejected, focal/sensor geometry supplies a labeled fallback, and no calibrated road-path overlay is drawn. Camera2 raw front input is treated as unmirrored; orientation and face coverage still require human bench checks. AHardwareBuffer EGL import is probed and reported, but remains disabled for inference until correctness and a measured speedup are established.

Backgrounding, lost surfaces, permission failure or a worker failure releases capture. Camera recovery has one bounded attempt; provider/hidden-ID startup failure is reported. In-app public metadata warmup replaces reliance on an ADB preflight, but repeated cold launch and post-reboot acceptance must be measured separately.

## Evidence and outstanding gates

The evidence index will contain the final installed build identity and measured sessions. `verification_passed=false` in a diagnostic session is intentional whenever any required gate remains unmet. Build success, a small OpenCL probe, average fps, CPU reference execution and a successful import probe each establish only their named property.

Required acceptance remains: all-output road/warp comparison and recurrent sequence regression; driver preprocessing/output comparison on representative inputs; independently verified simultaneous lens cadence/pairing; fresh 20 Hz driver output with suitable visibility; road cycle p95 at most 50 ms; 20-minute folded joint run; cold launches without shell preparation; lifecycle/provider/worker fault checks; and calibrated geometry/orientation. Face present/absent, looking away, eye closure, partial occlusion, glasses and low-light checks are bench observations, not validated driving protection.

No live camera pixels are recorded by default. Only text counters, probabilities, diagnostics, provenance and aggregate timings are retained. Previously flagged native host helpers remain disabled; reviewed standard-library Python checks and established trusted runners are allowed under the user's updated host-test policy.
