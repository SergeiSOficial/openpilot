# Fold 3 acceleration experiments

Checkpoint: 2026-10-29. The exact-order parallel CPU backend is accepted for
simulation on the physical Fold 3 and x86-64 emulator. Vehicle control is disabled.
GPU and QNN driving-model candidates remain separate experiments.

## Accepted results

| Matching foreground Fold 3 benchmark | Mean | p95 | Result |
| --- | ---: | ---: | --- |
| Original serial CPU | 193.12 ms | 194.53 ms | Reference |
| Exact-order parallel CPU | 141.53 ms | 145.01 ms | All 60 images, predictions and final states pass |
| Parallel CPU with FP16 compute tuning | 159.03 ms | 169.57 ms | Passes, slower; not selected |

The selected backend reduces standalone latency by **26.7%**. The full Android
service-process replay also passes: 60 model frames, 60 plans, all 12 daemon
comparisons and 170 captured simulated CAN messages. Replay elapsed time is
**20.987 s**; model execution mean is **156.97 ms**, p95 **167.61 ms**. This
remains above the 50 ms/20 Hz deadline. Both ABIs pass the integrated replay and
the corrupt CPU qualification hash check. Emulator timings do not predict phone
throughput.

The optimized emulator app also passes repeated Start/Stop/Reset, backgrounding,
required-worker death and corrupt-frame rejection. A further full 60-frame run
passes fold/unfold and landscape rotation without restarting the model worker.
The API 36 legacy fold profile needs the documented viewport workaround; this
is emulator evidence, not a physical unfolding test.

- [Matching phone benchmarks](../artifacts/android/acceleration/RFCR81Y1TBJ/20261028T160810Z/)
- [Accepted phone replay](../artifacts/android/acceleration/qualified-phone/5bde252c00e54bd9/)
- [Accepted emulator replay](../artifacts/android/acceleration/qualified-emulator/69bf2c25b0d7492e/)
- [ARM64 APK](../artifacts/android/acceleration/qualified-build/apk/debug/app-arm64-v8a-debug.apk)
- [x86-64 APK](../artifacts/android/acceleration/qualified-build/apk/debug/app-x86_64-debug.apk)
- [Fold/rotation report and dashboard captures](../artifacts/android/acceleration/qualified-emulator/ae1ba3b2b02e470d/)

## Model and measurement

All candidates use the original `driving_supercombo.onnx`, SHA-256
`65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce`.
The isolated test prepares an on-phone CPU reference from the same 60 canonical
NV12 pairs, fixed zero calibration and stationary small inputs. It compares
warped images, every raw prediction and final recurrent states. Float tolerances
remain `rtol=1e-4`, `atol=1e-5`; image and image-history bytes must match exactly.
The retained all-zero model reference is also checked before accepting a candidate.

These fixed-input measurements are separate from the full daemon replay in
[the original performance report](android-performance.md). Model-only timings
exclude replay startup, other daemons, reference comparison and disk loading.
CPU `ModelState` timings include warp and parsing. ORT timings, if qualified,
would include Java input transfer/output reading but exclude warp and parsing.

The initial phone experiment had no benchmark activity in front. Later tests
explicitly show the landscape dashboard and record affinity, nice and cgroup
information. Compare matching scheduling contexts; emulator timing is not a
prediction of phone throughput. Kernel profiling is sampled separately from the
timed sequence.

## Hardware access and rejected candidates

The ordinary unrooted APK can access Adreno OpenCL, including FP16. Its small
matrix/ReLU test had maximum absolute error `2.384185791015625e-7`. NNAPI exposes
`qti-default`, `qti-dsp` (accelerators), `qti-gpu` and the CPU reference device.
Hardware enumeration alone does not qualify the full model.

| Candidate | Physical-phone outcome |
| --- | --- |
| Retained CPU, standalone first reference | 60 pairs; mean 191.87 ms, p95 193.40 ms |
| ORT CPU | Rejected by the retained zero-input numerical gate |
| ORT NNAPI, CPU devices disabled | Session rejected: model cannot run on the selected devices |
| Original ONNX compiled for OpenCL | Executes, but rejected by the retained numerical gate |
| All kernels at ARMv8.2 FP16 / O3 | Rejected by sequence/image-history checks |
| First exact-order parallel CPU variants | Numerical checks pass; 390–473 ms means are slower and rejected |

The fresh ONNX GPU path no longer requires an on-device CPU compiler for shape
constants. Shape values are explicitly materialized on CL. This fixes execution,
not the remaining model accuracy discrepancy. The separate camera integration
is investigating the first divergent operation in the retained OpenCL graph;
it owns the shared `gpu.py`, `gpu_artifact.py` and `gpu_warp.py` implementation.

NNAPI fallback is not labelled NPU execution. The ORT candidate can record actual
execution providers from a separate profiling run if its numerical gate passes.
No driving-model candidate uses quantization or relaxed numerical tolerances.

## CPU partition implementation

`parallel_kernels.py` proves finite outer-loop output regions from the captured C
integer address expressions. It rejects output reads, escaped pointers, overlap,
out-of-range writes and expressions it cannot evaluate. Twenty-one compute
kernels qualify; the other 87 remain serial. Runtime input/output address overlap
falls back to a serial function without a no-alias assertion. The checked fast
path keeps the original no-alias information available to the compiler.

Each worker gets a private function stack. Inner loops, reduction order and
`-ffp-contract=off` remain unchanged. A separate FP16 candidate tunes only the
proven compute kernels, retaining baseline settings for queue movement, image
warping and every other kernel.

The latest pool uses a bounded spin before sleeping to avoid paying a full thread
wake-up for every short kernel. Native affinity is configured explicitly and
reported. The earlier four-lane phone experiment duplicated the caller's core
for one worker despite requesting CPU 4. Later Fold-specific experiments use
three lanes on CPUs 5, 6 and 7, which produced the accepted result above.
No system-wide governor, frequency, thermal or power settings are changed.

Using every CPU core was slower in earlier experiments. Other cores remain
available to Android, cameras and the other daemons. A certificate in the APK
binds the model assets and exact native library bytes; a corrupt hash fails
before selection. Model extraction is synchronized and its manifest replacement
is atomic.

Six reviewed standard-library tests verify valid regions, overlap/bounds
rejection, output-read rejection, unknown indices and the guarded fast/fallback
contracts. These checks do not compile or execute native host helpers. Native
libraries are cross-compiled for Android and tested inside the APK.

## Modern Qualcomm runtime, sensors and experimental GPU warp

The isolated QNN build uses ONNX Runtime **1.29.0**, Qualcomm ORT QNN plugin
**2.7.0** and QNN runtime **2.51.0**. Official Maven downloads are checksum
verified; the runtime includes the Fold 3's V68 HTP stub and DSP skeleton.

The physical phone passed a fresh, nonce-bound test with HTP selected and CPU
fallback disabled. A symmetric quantized convolution matches an independent
integer oracle for four patterns and 100 further runs. Its execution profile
contains **104 QNNExecutionProvider events and no CPU provider events**. This
establishes access to the Hexagon HTP/NPU/DSP path; those names do not identify
separate independent accelerators here. The phone was locked, so the test is
execution evidence, not foreground performance evidence. It does **not**
accelerate or qualify the driving model.

[Fresh QNN evidence](../artifacts/android/qnn/20261029T005029Z/) contains matching
attempt identity, app/test APK hashes, the provider trace and sensor cleanup.
An earlier nonce-less report was rejected and remains rejected evidence.
The [QNN documentation](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html)
defines HTP selection and disabling CPU fallback. Android deprecated NNAPI in
Android 15; see the [migration guide](https://developer.android.com/ndk/guides/neuralnetworks/migration-guide).
The direct QNN plugin is the current experimental Qualcomm path.

The original driving model was also tested with this newer runtime and a fresh
60-frame CPU reference. ORT 1.29 CPU produced non-finite output at the initial
model gate. QNN/HTP, with CPU fallback disabled, rejected the transformed
`model/node_conv2d_token_42` NHWC convolution because the provider did not claim
it. Neither candidate is selected. This is the observed runtime failure; it is
not evidence that all possible model conversions or Qualcomm configurations
cannot work. No driving-model quantization or tolerance relaxation was applied.
[Modern original-model evidence and tested APKs](../artifacts/android/acceleration/RFCR81Y1TBJ/20261029T021559Z/)
retains both failures and the passing fresh CPU reference.

`hybrid_gpu_cpu.py` passes its on-phone diagnostic gate: exact GPU-warped image
bytes, all 60 predictions and final recurrent states match a fresh CPU reference.
CPU out-of-band weights are explicitly allocated in a CPU device context even
while the warp default is CL. It supports independent pixel checks at other
camera dimensions without on-device CPU warp code generation.
[Hybrid evidence](../artifacts/android/acceleration/RFCR81Y1TBJ/20261029T010600Z/gpu_hybrid-2.json)
was collected while locked, so timing is explicitly unqualified. The candidate
is not selected automatically and does not qualify the full-model GPU backend.
The coordinated camera work owns shared GPU/live/camera integration.

Camera2 uses the phone camera pipeline and ISP; capture and lifecycle evidence
is maintained in [live shadow documentation](android-live-shadow.md). ISP access
does not qualify vehicle camera geometry.

`HardwareSensors` collects accelerometer and uncalibrated gyro values, bias
fields and BOOTTIME timestamps in bounded buffers. The latest 10-second probe
receives both streams at approximately **103.5 Hz**, with finite values,
monotonic timestamps and clean listener/thread shutdown. Samples remain in the
raw phone frame; mount calibration and locationd integration are unqualified.

GPS is enabled by the user. Location, satellite-status and raw GNSS callbacks
register, but the bounded indoor/locked-screen probe receives no fix or
satellite/raw callbacks. It records `no_fix_received` without fabricating
location or asserting locationd validity. The user's enabled setting is preserved.

## Reproduce

Builds use a separate WSL mirror, `project-acceleration`, and application ID
`ai.comma.openpilot.acceleration`. They do not replace the simulation or Samsung
live-camera app. Ordinary Android regression suites do not include the isolated
benchmark source set.

```powershell
py -3.12 -m unittest discover -s tools/android/tests -p test_parallel_proof.py -q
wsl -d Ubuntu-24.04 -- bash tools/android/build-parallel-kernels.sh
py -3.12 tools/android/qualify_cpu.py --phone artifacts/android/acceleration/RFCR81Y1TBJ/20261028T160810Z/cpu_parallel-2.json --emulator artifacts/android/acceleration/emulator-5556/20261028T155406Z/cpu_parallel-2.json
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PqualifiedCpu
py -3.12 tools/android/test_acceleration.py --serial RFCR81Y1TBJ --install --backends reference cpu_parallel cpu_parallel_v82

py -3.12 tools/android/prepare_qnn.py
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn
py -3.12 tools/android/test_qnn.py --serial RFCR81Y1TBJ
py -3.12 tools/android/test_acceleration.py --serial RFCR81Y1TBJ --install --modern-qnn --backends reference cpu qnn --candidate-timeout-seconds 120

# Optimized emulator fold/rotation test with console acknowledgements:
./tools/android/test-emulator.ps1 -Package ai.comma.openpilot.acceleration -ApkRoot artifacts/android/acceleration/qualified-build/apk -TestClass 'ai.comma.openpilot.sim.LifecycleTest#foldingAndRotationPreserveSixtyFrameSimulation'
```

Coordinate a quiet phone window before timing. The test keeps the Fold 3 closed,
preserves the display-size override and shows its landscape dashboard. It writes
dated JSON reports, test logs, APK hashes and thermal snapshots under
`artifacts/android/acceleration/<serial>/`. Rejected candidates are retained and
the orchestration command returns a nonzero status when any requested candidate
fails. Reference preparation and all model/native execution happen on Android.

Initial device capability evidence:
[Fold 3 capabilities](../artifacts/android/acceleration/RFCR81Y1TBJ/capabilities-2.json).
The first exact-order hybrid pool's emulator sequence passed all 60 frames:
[emulator report](../artifacts/android/acceleration/emulator-5556/20261028T152231Z/cpu_parallel-2.json).
This is correctness evidence; it does not establish a phone speedup or the
50 ms driving-model deadline.

Wait for each build to complete before installing its APKs. The acceleration
runner rejects stale attempt IDs and records actual window focus, screen and
keyguard state. Correctness with a locked phone does not qualify timing. Restore
the accepted CPU APK after the separate QNN experiment. Accepted APKs have the
label `openpilot Simulation (optimized CPU)`; diagnostic builds use the same
isolated application ID and do not replace the baseline or Samsung live app.
