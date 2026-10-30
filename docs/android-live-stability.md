# Fold3 live pipeline: stability and qualification

The live APK owns a separate `:sensord` worker. It collects approximately 100 Hz
accelerometer/uncalibrated gyro and 1 Hz Android GPS callbacks independently of
model initialization. Recorded replay does not start this worker. Vehicle
actuation stays disabled.

## Default operation

Live Shadow runs the verified dual-rear camera configuration without opening the
front camera. Cabin Diagnostic is a separate mode. Rear Capture Diagnostic also
runs the sensor publisher. A rejected or absent road backend leaves capture and
sensors running with `pipeline_state=inference_blocked` or `capture_only`.

IMU queues hold at most 512 samples per stream, dropping the oldest on overflow;
GPS holds at most 32 pending fixes. Publication rejects samples older than 100 ms
(IMU) or two seconds (GPS), future timestamps, duplicates, non-finite data and
mock locations. Gyro bias is reported separately and is not silently subtracted.
Missing optional GNSS fields prevent a fully valid GPS packet; no vertical
velocity or outdoor fix is invented. A no-fix heartbeat explicitly has no fix.
After the bounded startup grace, an IMU freshness miss pauses inference
immediately; two seconds of persistent loss terminates the session. Healthy
report-file heartbeats alone cannot conceal a stopped sensor stream.

BOOTTIME measurements are converted to MONOTONIC. Offset discontinuities above
5 ms increment a clock generation; live road inference is blocked after a
generation change. Uncalibrated IMU packets have Android source and invalid
localization status. `locationd` also requires qualified camera odometry and
camera geometry; GPS is published independently because this version's
`locationd` does not consume it.

`sensors.json`, `sensor-cleanup.json`, `camera.json` and `progress.json` retain
counts, freshness, gyro bias, queue overflow, process PSS, thermal status and
calibration state. Timing percentiles describe the most recent 4,096 samples;
counters, camera gaps and queue overflow cover the session. Camera packing and
snapshot timing include explicit lock-wait and copy measurements. No live pixels
are saved.

## Mount calibration

The default is uncalibrated. UI rotation never changes sensor axes. The profile
maps Android natural-orientation axes into the existing openpilot sensor input
basis, before `locationd` applies its own `[-z, -y, -x]` mapping. Do not apply that
mapping twice. Changing the physical mounting requires a new calibration.

Collect physical gravity observations along at least three independent
directions and known rotations about x/y/z. Supply measured Android vectors and
the independently known expected sensor-frame vectors to the reviewed tool:

```powershell
py -3.12 -B tools/android/mount_profile.py measured-observations.json --output mount-calibration.json
adb -s RFCR81Y1TBJ push mount-calibration.json /data/local/tmp/openpilot-mount-calibration.json
adb -s RFCR81Y1TBJ shell run-as com.samsung.android.openpilot.shadow cp /data/local/tmp/openpilot-mount-calibration.json files/mount-calibration.json.tmp
adb -s RFCR81Y1TBJ shell run-as com.samsung.android.openpilot.shadow mv files/mount-calibration.json.tmp files/mount-calibration.json
```

The tool documents its input format and physical tolerances, preserves the
observations and hashes their canonical JSON. It checks supplied measurements;
it does not perform or certify the physical procedure. Start a fresh session
after installing a profile.

## Acceleration gate and thermal behavior

No slow CPU road fallback is selected. The original OpenCL numerical diagnostic
remains available under GPU validation. The isolated QNN experiment remains
separate; HTP/NPU/DSP names refer to the same Qualcomm acceleration path here.

Live road selection requires private `files/road-qualification.json`. The
`live_policy.qualification_passed` contract requires model/source/native hashes,
runtime, driver and device fingerprint to match the current APK, physical
SM-F926B evidence, exact images, a strict numerical pass, at least 60 sequence
frames, unchanged tolerances, and a 1,200-second joint run with at least 19.5
fresh outputs/s, cycle p95 at most 50 ms and maximum pairing skew at most 10 ms.
No such certificate is created by the build or by a small accelerator probe.
A deadline violation or clock discontinuity blocks live road selection again.

Severe thermal status pauses inference and thumbnail work; recurrent road state
is reset. Critical status stops capture and sensor ownership. Startup while
severe/critical is rejected; restart explicitly after cooling. Thermal headroom
is sampled at most every ten seconds. Performance hints are optional and do not
change CPU governors, power settings or thermal policy.

## Verification

Host checks use reviewed Python standard-library tests. Native packing and
message publication execute only in Android instrumentation:

```powershell
py -3.12 -B -m unittest discover -s tools/android/tests -p 'test_live*.py' -q
py -3.12 -B tools/android/tests/test_mount_profile.py -q
./tools/android/build-live.ps1
adb -s RFCR81Y1TBJ install --no-incremental -r -g android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk
adb -s RFCR81Y1TBJ install --no-incremental -r android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s RFCR81Y1TBJ shell am instrument -w -r -e class ai.comma.openpilot.sim.LivePipelineTest,ai.comma.openpilot.sim.ReplayTest com.samsung.android.openpilot.shadow.test/androidx.test.runner.AndroidJUnitRunner
py -3.12 -B tools/android/test_live.py --serial RFCR81Y1TBJ --mode live --duration 1200
py -3.12 -B tools/android/test_live.py --serial RFCR81Y1TBJ --mode cabin --duration 1200
py -3.12 -B tools/android/test_live_lifecycle.py --serial RFCR81Y1TBJ
```

Foreground runners require the phone unlocked and folded. Physical mount checks,
an outdoor GNSS fix, camera geometry, numerical/model qualification, sustained
performance and lifecycle checks are separate acceptance outcomes. Missing
evidence leaves the corresponding gate unqualified.
