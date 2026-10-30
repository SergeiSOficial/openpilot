# Fold3: root-free simultaneous rear-camera capture

Verified on 2026-10-28 on the connected **SM-F926B**, folded and unlocked, Android 15 / API 35, firmware **F926BXXSJJZH3**. Two independent rear lenses streamed simultaneously through Samsung's private camera interface. This supersedes the earlier conclusion that no working app-only configuration had been found.

This is a camera-access prototype, not OpenPilot driving acceptance. No production capture integration was added.

## Working session

The self-signed diagnostic uses the unique application ID `com.samsung.android.openpilotprobe`. No Samsung application needs replacing. Two other, previously absent Samsung package names were tried during investigation and subsequently removed; neither was necessary for the working recipe.

1. Query and open hidden logical rear camera **20**. This groups physical IDs `0`, `2` and `52`. Public `getCameraIdList()` still lists only `0`, `1`, `2`, `3`, and `getConcurrentCameraIds()` still returns an empty set.
2. Load the installed `/system/framework/scamera_sdk_util.jar` with `PathClassLoader` and invoke `CustomInterfaceHelper.setSamsungParameter(CameraDevice, String)`. Send Samsung's initial parameters with `first-entrance=true`, `samsungcamera=true`, `factorytest=false`, `shootingmode=0`, then the session parameters with `first-entrance=false`, `shootingmode=3`, and `recording-fps=30`. The complete strings are in the source. This calls Samsung's framework `CameraDevice.setParameters`, without modifying the framework or hidden-API enforcement policy.
3. Configure a real **SurfaceView display preview** plus two `YUV_420_888` ImageReaders. A PRIVATE ImageReader is not an equivalent preview: its consumer usage made Samsung classify it as a preview callback, leaving the required display-preview pointer absent. Early configurations then crashed the vendor camera provider.
4. Mark outputs using Samsung's stream-role encoding through `OutputConfiguration.setStreamUseCase(role << 16)`:

   | Output | Samsung role | Stream-use-case value |
   |---|---:|---:|
   | Display preview | `0x1` | `65536` |
   | First YUV callback | `0x1` | `65536` |
   | Extra YUV callback | `0x101` | `16842752` |
   | Passive JPEG output | `0x2` | `131072` |

   The tested session also configured a 4000×2252 JPEG output. No JPEG request was submitted and no image was saved. Its necessity has not been isolated.
5. **Do not bind these outputs with `setPhysicalCameraId`.** The standard physical-output path could configure with the added display preview, but Android terminated it on the first results: `Expected physical Camera metadata count 2 not equal to actual count 0`. The working Samsung-role session leaves the physical ID unset on every output.
6. Add the display and both YUV surfaces to one repeating preview request, requesting an advertised logical frame-rate range of `[30,30]`.

The runner collects a read-only `dumpsys media.camera` preflight before each test. Hidden-ID queries sometimes failed after provider restarts until this preflight was performed. The preflight is part of the verified procedure; reliable standalone cold startup without ADB, including after reboot, is **not established**. The prototype should not silently be treated as a deployable camera service.

## Physical verification

The user placed the folded phone facing a lit scene and individually covered the top, middle and bottom rear lenses while both streams continued. Each stream had changing image hashes, rather than a frozen fallback image.

| Observed phase | Stream 0 median luma | Stream 1 median luma |
|---|---:|---:|
| Uncovered reference | 112.24 | 97.74 |
| Top lens covered | 98.51 | 99.84 |
| Middle lens covered | **32.43** | 99.34 |
| Bottom lens covered | 98.95 | **22.61** |

This establishes independent middle-lens and bottom-lens capture. The logical metadata reports a 5.0 mm focal length for the main view. The extra stream does not provide trustworthy per-sensor Camera2 metadata, so its intrinsics and precise field of view still require direct calibration. No calibrated sensor assignment should be inferred solely from logical result metadata.

The uninterrupted 180-second acquisition completed without reported capture failures:

| Measurement | Stream 0 | Stream 1 |
|---|---:|---:|
| YUV dimensions | 1920×1080 | 1920×1080 |
| Received frames | 5,389 | 1,752 |
| Timestamp-derived average frame rate | 30.002 fps | 9.748 fps |
| Largest inter-frame timestamp gap | 66.62 ms | 733.13 ms |
| Nonmonotonic timestamp events | 0 | 0 |

Nearest-frame timestamp differences had a **33.31 ms median** and **366.52 ms maximum**. This is a buffer-timing comparison, not exposure synchronization. It does not establish synchronized stereo capture or the timing required by OpenPilot.

Additional 10-second tests at 1280×720 and with a video shooting-mode session key gave roughly 30 fps for stream 0 and 11.25 / 11.23 fps for stream 1. They did not solve the secondary stream's rate limitation. A final 30-second test with live thumbnail rendering also retained two streams, at 29.97 and 10.45 fps.

## Reproduce

From the repository root in PowerShell, with the existing Java 17 and Android SDK tools:

```powershell
python tools/android/camera_probe/build.py
adb -s <serial> install --no-incremental -r -g tools/android/.cache/camera-private/probe.apk
python tools/android/camera_probe/run.py --serial <serial> preview20-sustained
```

Use the selected physical SM-F926B serial, not the emulator. `run.py` verifies the model before executing. The runner can test experimental cases, some known to crash the vendor provider; use `preview20-sustained` for the working recipe.

The installed **Fold Camera Probe** launcher runs the working layout for 60 seconds, then closes the camera. Two grayscale thumbnails refresh once per second; their display refresh rate is separate from capture frame rate. After a provider restart, first run the ADB preflight procedure above. The app is a diagnostic, with no vehicle-control or network permission. Results are text-only under its private `files/result.txt`; pixels are displayed transiently and are not saved.

Source: `tools/android/camera_probe/Probe.java`, `build.py`, `run.py`, `summarize.py`.

Durable evidence: `tools/android/camera_probe/evidence/fold3-lens-check.txt` and `fold3-lens-check.json`. Raw diagnostics, stock-APK/framework inspection copies and additional runs remain in the ignored `tools/android/.cache/camera-private/` directory. The APK contains Java/Dex, not a generated host executable or a packaged native library. Only the existing SDK tools executed on the host; camera validation ran on the phone. No root, bootloader unlocking, firmware modification, security-policy change, or endpoint-protection workaround was used.

## Remaining OpenPilot work

- Raise and stabilize the secondary stream rate; quantify latency, drop behavior and exposure timing under sustained load and temperature.
- Establish independent camera intrinsics, distortion, field of view and extrinsics, rather than borrowing comma-device calibration.
- Resolve cold-start access and phone lifecycle behavior without diagnostic ADB preparation.
- Implement the Android capture-to-VisionIPC path with correct metadata and frame pairing. The current Android app remains the recorded-fixture simulation port.

The existing `modeld.py` flags a main/extra timestamp difference exceeding 10 ms. The measured nearest-frame distribution and secondary rate do not satisfy a claim of driving readiness. Camera-access success must remain separate from model, controls and hardware acceptance.

References used to guide investigation: [Android multi-camera API](https://developer.android.com/media/camera/camera2/multi-camera), [AOSP multi-camera implementation](https://source.android.com/docs/core/camera/multi-camera), and [Samsung interface reverse-engineering notes](https://gist.github.com/tdrkDev/c2e4f66481b5d5fb12f1245ded4fc49b). The working recipe and results above were verified on this phone, not assumed from those sources.
