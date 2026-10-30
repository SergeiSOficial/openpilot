# Experimental Fold 3 QNN quantization

The experiment has its own package, `ai.comma.openpilot.qnn`, labelled
`openpilot Quantized Simulation (experimental)`. It does not replace the accepted
`ai.comma.openpilot.acceleration` CPU APK or select a backend in Live Shadow.
Physical CAN actuation is disabled.

## Preparation and numerical contracts

The default road model SHA-256 remains
`65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce`.
The target runtime is ORT 1.29.0, QNN plugin 2.7.0 and QNN runtime 2.51.0.
Static graph tools live in a separate WSL virtual environment; the target
Python/native dependency lock and retained model are unchanged.

`qnn_graph.py` records every FP16-to-FP32 conversion, preserves byte image/history
interfaces, and produces FP16, FP32 and internal U16/U8 convolution probes.
ORT adds `_token_<counter>` to generated duplicate names: the rejected
`model/node_conv2d_token_42` is traced toward the first convolution, rather than
assuming it means original `node_conv2d_42`. The manifest labels mapping status
explicitly; target provider diagnostics are retained for confirmation.

The road FP32 graph contains an intentional negative-infinity attention mask.
A separate finite masked-softmax formulation uses the row minimum to replace
masked logits before normalization, then zeros masked exponentials. It applies
no arbitrary numeric floor. Fully masked rows still fail finite-output checks.
The original formulation is retained for on-target comparison.

The first emulator test completed 60 frames: both FP32 formulations were finite,
repeatable, and matched at `rtol=1e-4`, `atol=1e-5`. They did not match the retained
FP16 CPU reference. This is calibration-graph validation, not model accuracy or
physical HTP qualification. Evidence:
`artifacts/android/acceleration/emulator-5556/20261029T091004Z/`.

## Capture, calibration and execution

The Android reference runner saves all 60 warped frame pairs, actual incoming
recurrent states, small inputs and outputs with hashes. This fixture benchmark
uses fixed zero calibration and stationary small inputs; it does not establish
coverage of general driving conditions.

Frames 1–40 supply calibration only; frames 41–60 are holdout. The instrumented
FP32 graph exposes 379 tensors in 48 fetch groups, each at most eight tensors and
128 MiB. Groups resume only when graph/capture hashes match. Non-finite values,
partial ranges, different graphs and incorrect frame splits are rejected.

The host uses official QNN configuration and `QDQQuantizer` with measured ranges,
uint16 activations and uint8 weights. Host inference is explicitly blocked.
Every resulting model must still pass target compilation and execution.

The explicit `qnn_quantized` diagnostic runs teacher-forced and independently
evolving states against both the quantized CPU reference and original outputs.
Hardware execution, quantized-reference agreement and original-reference
agreement are separate outcomes. HTP runs disable CPU fallback and require a
QNN-only execution-provider trace. No accuracy tolerance is relaxed.

## Explicit road and cabin roles

`qnn_graph.py`, `stage_acceleration.py`, `test_acceleration.py`, and
`test_qnn_experiment.py` accept `--model road|cabin`; omission preserves the road
default. The build wrapper forwards `-PqnnModel=cabin` to cabin staging.
Graph caches are `tools/android/.cache/qnn-quantized` for road and
`tools/android/.cache/qnn-quantized-cabin` for cabin. The staged manifest, original
model hash, capture, calibration ranges, finite/repeatable gate, execution gate,
and final report must agree on the role. Older role-less evidence is accepted
only as road, with its original source and graph hashes still required.

The original cabin model is `dmonitoring_model.onnx`, SHA-256
`dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04`.
Its interface remains byte `input_img[1,1382400]`, FP32 `calib[1,3]`, and FP16
`outputs[1,553]`. FP32 preparation widens internal arithmetic and adds an explicit
output cast to preserve the original external FP16 interface. It applies no
road attention-mask rewrite. Static cabin preparation exposes 202 calibration
tensors in 26 bounded fetch groups; this does not establish target support.

The cabin reference phase feeds recorded narrow-road fixture luma through the
existing complete cabin pixel oracle and executes the unchanged original cabin
ONNX model with Android ORT CPU. The corpus records byte inputs, fixed zero
calibration, native FP16 outputs, the transform, fixture hash, source hash, and
per-frame hashes. Outputs must be finite and repeatable. These fixture images
do not establish face coverage, driver-monitoring accuracy, or live acceptance.
No live images are saved by this experiment.

Road uses `capture`, `qnn-ranges.json`, and existing gate filenames. Cabin uses
`capture-cabin`, `qnn-ranges-cabin.json`, and gates ending in `-cabin.json`.
Both reserve frames 1–40 for calibration and 41–60 for holdout. Road evaluation
uses teacher-forced and free recurrent states; cabin evaluation is stateless.
Every frame records original-reference error separately from quantized-CPU
reference error, using the unchanged `rtol=1e-4`, `atol=1e-5`.

Use `--capture <exported-capture-directory>` when moving the corpus from emulator
calibration to physical HTP execution. The tool checks all 60 file hashes, role,
original source hash and split before transferring a fixed whitelist into the
isolated QNN app. Quantized evaluation requires the exact capture-manifest hash
used by its measured ranges. A successful HTP execution report can still show
original-reference disagreement; it does not become an accuracy certificate.

## Reproduce

Run each build to completion before installing. Coordinate phone access with the
camera work. Use the emulator for CPU-only calibration while the phone is busy;
its CPU runtime is also pinned to ORT 1.29.0. Emulator execution never proves NPU
availability. Record the calibration device and validate HTP on the Fold 3.

```powershell
wsl -d Ubuntu-24.04 -- bash tools/android/bootstrap-qnn-graph.sh
py -3.12 -m unittest discover -s tools/android/tests -p test_qnn_graph.py -q

# Physical HTP support and finite/repeatable FP32 checks:
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized
py -3.12 tools/android/test_qnn_experiment.py --serial RFCR81Y1TBJ --phase prepare --install --restore-default

# CPU-only emulator calibration:
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized -PqnnCpuEmulator
py -3.12 tools/android/test_qnn_experiment.py --serial emulator-5556 --phase prepare --install
py -3.12 tools/android/test_qnn_experiment.py --serial emulator-5556 --phase calibrate

# Supply the exported qnn-ranges.json from the dated evidence directory:
wsl -d Ubuntu-24.04 -- /home/dey/.cache/openpilot-android/qnn-graph-venv/bin/python tools/android/qnn_graph.py --ranges <WSL-path-to-qnn-ranges.json>
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized
py -3.12 tools/android/test_qnn_experiment.py --serial RFCR81Y1TBJ --phase evaluate --install --restore-default
```

The completed road calibration is retained at
`artifacts/android/qnn-experiment/emulator-5556/20261029T092522Z/qnn-ranges.json`.
It binds 48 completed groups to the exact instrumented road graph and capture.
Full-road HTP support and numerical agreement remain target gates.

The first full-road QDQ test on the Fold3 is recorded in
`artifacts/android/qnn-experiment/RFCR81Y1TBJ/20261029T131453Z/full-road-summary.json`.
The exact emulator corpus was exported before changing its app data; its manifest
hash remains `02a4f9f6b389ada043b5f8aa8a32236c3ae13a88186ab846bea7855440b1e292`.
Both quantized CPU modes completed 60 frames, but disagreed with the original
model (maximum output error 22.2664). HTP executed zero frames: ORT rejected
ReduceL2, byte-history Concat/Gather, GatherND and a feature Slice when CPU
fallback was disabled. The accepted CPU APK hash was verified unchanged.

`--supported-road-forms` prepares a separate candidate in
`tools/android/.cache/qnn-quantized-road-supported`. It expands the two static
ReduceL2 operations into Mul/ReduceSum/Sqrt, replaces a contiguous constant
GatherND with Slice, bypasses a verified FP32 identity cast for the feature Slice,
and flattens byte-history copies while restoring every external shape. Byte-copy
operations receive explicit scale1/zero0 uint8 QDQ metadata: every integer0..255
is exactly representable in FP32 and requantizes unchanged. These are candidate
formulations; static checks do not establish HTP support.

The supported candidate retains the preceding experimental FP32 graph byte for
byte as `fp32_baseline`. Its target gate compares all 60 frames at the original
tolerance and requires exact byte-state outputs. The new instrumented graph
exposes 383 tensors in 48 groups. Its changed hash requires fresh calibration;
the older 379-tensor range document cannot be substituted or relabelled. New
calibration records also bind the calibration device fingerprint and ORT version.

Build a separately selected graph cache with
`'-PqnnGraphRoot=tools/android/.cache/qnn-quantized-road-supported'` (quote the
entire property in PowerShell), or pass
`--graph-root` directly to `stage_acceleration.py`. First run `qnn_fp32` with the
exact exported corpus, then calibrate that candidate, then prepare its QDQ graph
using only its own new ranges. Full HTP provider attribution and both reference
comparisons remain required afterward.

The supported road candidate passed the 60-frame target CPU comparison against
its preceding experimental FP32 baseline. Fresh emulator calibration completed
all 48 groups / 383 tensors in
`artifacts/android/qnn-experiment/emulator-5556/20261029T142152Z/`.
Its range SHA256 is
`0964452045c8d0f055b33c90854d23330d06b358f525fd967786a968defb9cba`;
the range record includes the emulator fingerprint and ORT 1.29.0. This is
calibration evidence, and still requires physical HTP execution and comparison.

The first physical run of that supported graph completed both 60-frame CPU
modes, but HTP validation rejected only `node__unsafe_view` and
`node__unsafe_view_1`. Their quantized UINT8 inputs and raw UINT8 outputs differed
because the following byte-to-float Cast registered the output without scale1
metadata. Evidence is in
`artifacts/android/acceleration/RFCR81Y1TBJ/20261029T151146Z/`.
The separate `--u8-cast-dq` candidate changes those two Casts to exact
DequantizeLinear(scale1,zero0). Every code 0..255 converts identically to FP32;
the FP32 calibration expressions and their names are unchanged. Its manifest
records this post-quantization composition, retains the preceding QDQ graph
byte-for-byte as a baseline, and requires all 60 teacher-forced and 60 free-state
CPU frames to agree before HTP is attempted. No older range document is relabelled.

The byte-DQ candidate subsequently executed all 60 teacher-forced and 60 free-state
frames on the physical HTP with CPU fallback disabled. Both profiles contained
only QNNExecutionProvider events. Its CPU comparisons against the preceding QDQ
graph passed, while strict HTP-versus-quantized-CPU agreement and original-model
agreement failed. The 20-minute test remains gated. The bound result is
`artifacts/android/qnn-experiment/RFCR81Y1TBJ/20261029T152403Z/full-road-hardware-summary.json`;
raw profiles and native/APK identities are retained alongside the target report.
Execute-only p95 was 18.79 ms / 17.80 ms; this is recorded-fixture evidence.
Transfer/download timings may include lazy NPZ decoding, and preprocessing,
parsing and live capture are not covered by those execute-only numbers.

The intermediate diagnostic at
`artifacts/android/acceleration/RFCR81Y1TBJ/20261029T160649Z/` used identical inputs
and confirmed that its final CPU and HTP outputs matched their unchanged base
graphs. Both raw byte imports and exact byte-to-float conversions matched bit
for bit. The first failing selected probe was the pre-Conv Sub dequantization;
the earlier cat requantization lies between those probes. The separate
`--normalization-lut` candidate derives its 256-entry UINT16 table from the
unchanged CPU QDQ normalization formula and recorded scales. It retains that
full QDQ graph as its CPU baseline, leaves calibration and original model bytes
unchanged, and requires an all256 CPU/exact-HPT-code operator gate followed by
both full60 CPU equivalence modes before attempting full-model HTP. The table
is not fitted to accelerator errors.
The initial incomplete scalar table failed the target CPU gate at 83 byte values,
including clipping differences up to 812 UINT16 codes, before HTP was attempted
(`artifacts/android/acceleration/RFCR81Y1TBJ/20261030T084131Z/`). The authorized
CPU-oracle mode reads that unchanged ORT expression graph's exhaustive codes,
verifies the actual APK, source/reference graph, native libraries and build
manifests, and records their hashes in the new manifest. The independent scalar
oracle remains separate. The missing step was the input QDQ before cat: camera0
uses range239, whereas camera1/cat use range242. Including it explains every
captured CPU code. The candidate therefore uses two distinct camera tables and
records which table was captured versus derived pending the fresh CPU gate.
The target gate repeats all bytes across 24 channels
under three position permutations, then requires both full60 CPU baseline modes.
An additional CPU stage-output graph is retained to inspect every quantization
boundary; exposing its outputs must not be confused with the unchanged oracle.
The corrected two-camera candidate is
`2f160328f3c2f9a5fd05b5b241722cb240af9b2d09e317dd039c95602796c892`.
Its private physical APK is retained under
`artifacts/android/qnn-experiment/road-two-camera-lut-build/` with SHA-256
`2a4aed98345991bea7d05032804f6b542da7504097b832e49767802fbac5ac9b`.
The app and test APK passed binary Android manifest, DEX, resources, ZIP CRC,
signature and WSL/Windows hash checks. These packaging checks are recorded
separately from the following target evidence.
The explicit `qnn_preprocess_cpu` backend can run the same CPU comparisons on
Android without attempting HTP or issuing a normalization proof:

```powershell
py -3.12 -B tools/android/test_acceleration.py --serial emulator-5556 --model road --qnn-experiment --modern-cpu-emulator --backends qnn_preprocess_cpu
```

Select and install the matching private x86_64 emulator build first. This CPU-only
result cannot authorize full-model HTP execution or a timing qualification.
The emulator ORT 1.29.0 run at
`artifacts/android/acceleration/emulator-5556/20261030T103954Z/`
passed bit-exact comparison for all 256 byte values across all 24 channels and
three position permutations. Both camera tables matched the unchanged CPU
reference, and the additional stage-output graph preserved the final results.
It reported `hardware_execution=false`, wrote no HTP proof, and explicitly left
timing unqualified. An emulator CPU pass cannot substitute for either physical
operator or full-model checks.

The physical Fold3 operator gate then passed at
`artifacts/android/acceleration/RFCR81Y1TBJ/20261030T104346Z/`:
all 256 values across 24 channels and three permutations matched the unchanged
CPU expression, HTP UINT16 codes were exact, and HTP float outputs met the
original tolerance. Its QNN-only profile was exported and hash checked.
The subsequent full-model run at `20261030T104452Z/` completed all 60
teacher-forced and 60 free-state frames. Both candidate CPU modes were bit-exact
against the unchanged `82e77a74...` quantized baseline (maximum error zero),
and both HTP profiles contained 60 QNNExecutionProvider events with CPU fallback
disabled. Strict HTP-versus-quantized-CPU agreement still failed with maximum
error 34.931488; original-model agreement failed with maximum error 35.566895.
The 20-minute test remains gated, and the candidate remains unqualified.
Execute-only p95 was 20.82 ms teacher-forced and 21.51 ms free-state; these
prewarped-fixture timings exclude capture, preprocessing, upload, download and
parsing. They are not fresh-camera FPS. The compact
`full-road-lut-summary.json`, three raw profiles and actual APK/native identity
checks accompany those reports. The full-graph intermediate diagnostic is a
separate experiment because the exact small operator did not repair full-model
agreement; its operations and constants remain unchanged.
That diagnostic subsequently ran on Fold3 at
`artifacts/android/acceleration/RFCR81Y1TBJ/20261030T111055Z/`.
Its CPU and HTP final outputs each matched their respective unchanged base
graph, and both HTP profiles contained only QNNExecutionProvider events.
With identical input hashes, both image imports and full-size normalization
UINT16 codes were bit-exact. Normalization float DQ differed by at most
2.3841858e-7, within the unchanged tolerance. The first failing selected stage
was the first Conv: its UINT16 output differed by up to 21 codes, with float
DQ error 0.0437622; the following activation and Conv errors were 0.0528755 and
2.220058 respectively. Four raw NPZ files and both profiles were exported and
hash checked. This localizes the remaining failure to the first Conv boundary;
an identical-input Conv experiment is still needed before changing its
quantized arithmetic or attributing the cause to small float DQ differences.
Before any future sustained run, the execution certificate must also contain
the exact current native-runtime SHA-256 map; missing, malformed, incomplete or
changed library identities reject the run. This source guard was added after
the diagnostic APK snapshot and passed reviewed stdlib tests. The retained
diagnostic APK predates that guard and cannot provide a new sustained-run
certificate. Its numerical failures already block the 20-minute test.

For the separate cabin experiment, first prepare its static graphs, then collect
and calibrate its original-model corpus on Android. These commands are a workflow
for a coordinated future target run, not evidence that HTP has passed:

```powershell
wsl -d Ubuntu-24.04 -- /home/dey/.cache/openpilot-android/qnn-graph-venv/bin/python -B tools/android/qnn_graph.py --model cabin
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized -PqnnCpuEmulator -PqnnModel=cabin
py -3.12 -B tools/android/test_qnn_experiment.py --model cabin --serial emulator-5556 --phase prepare --install
py -3.12 -B tools/android/test_qnn_experiment.py --model cabin --serial emulator-5556 --phase calibrate

# Supply this cabin run's exported ranges and matching capture-cabin directory.
wsl -d Ubuntu-24.04 -- /home/dey/.cache/openpilot-android/qnn-graph-venv/bin/python -B tools/android/qnn_graph.py --model cabin --ranges <WSL-path-to-qnn-ranges-cabin.json>
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized -PqnnModel=cabin
py -3.12 -B tools/android/test_qnn_experiment.py --model cabin --serial RFCR81Y1TBJ --phase evaluate --capture <exported-capture-cabin-directory> --install --restore-default
```

The first full cabin target attempt executed 60 frames with the experimental
quantized CPU reference, but HTP session creation rejected its final FP32-to-FP16
Cast. Its original-model numerical comparison failed; its timing is unqualified.
The separate `--cabin-output-dq` candidate replaces only that final DQ/Cast
boundary with standard DequantizeLinear-23 and explicit FP16 output. It retains
the measured FP32 scale bytes, the original external interface, and the preceding
quantized graph as `quantized_baseline`. The calibration graph and measured ranges
are unchanged. Because the main ONNX opset advances from 20 to 23, every one of
the 60 target CPU frames must match that baseline at the existing tolerance
before HTP execution is attempted. Static validation alone does not pass that
gate. Prepare and select this candidate explicitly:

```powershell
wsl -d Ubuntu-24.04 -- /home/dey/.cache/openpilot-android/qnn-graph-venv/bin/python -B tools/android/qnn_graph.py --model cabin --cabin-output-dq --ranges <WSL-path-to-qnn-ranges-cabin.json>
wsl -d Ubuntu-24.04 -- bash tools/android/build-acceleration.sh -PmodernQnn -PqnnQuantized -PqnnModel=cabin '-PqnnGraphRoot=tools/android/.cache/qnn-quantized-cabin-output-dq'
```

That candidate's physical CPU gate failed before frame 1 in
`artifacts/android/acceleration/RFCR81Y1TBJ/20261029T150023Z/`:
the packaged ORT 1.29.0 DequantizeLinear kernel requested `MutableData<float>`
for the declared FP16 output. HTP was not attempted. This is a retained runtime
compatibility failure, and no output conversion was moved to CPU fallback.
An isolated `qnn_boundary` probe can separately test the exact FP32-scale to FP16
DQ boundary on HTP over every UINT16 code. Its expected values are computed on
Android using the original FP32 dequantization formula and final FP16 rounding;
it checks provider attribution and preserves the same scale bytes. An operator
probe never replaces the full-model gate or supplies an accuracy certificate.
The single-DQ probe validated the operation but was refused by the plugin's
single-quantization-node partition policy. A two-operation probe reached session
creation and then exposed the public Java UINT16-input factory mapping to INT16.
The revised probe accepts FLOAT32 values on the existing quantization lattice,
also returns every UINT16 code, and requires all 65,536 codes and FP16 results to
match exactly. Only that identity-bound physical proof can authorize the composed
experimental reference (preceding unchanged CPU graph plus proven output
boundary) when the candidate's ORT CPU kernel remains unavailable. Full 553-value
original and quantized-reference comparisons remain mandatory.
The physical FLOAT32-lattice probe at
`artifacts/android/acceleration/RFCR81Y1TBJ/20261030T092453Z/` executed on QNN and
returned all 65,536 intermediate UINT16 codes exactly. Its decoded FP16 results
failed the unchanged tolerance (maximum difference 0.00390625). No proof was
issued and the full cabin model stayed gated. This is a measured arithmetic
contract mismatch, not evidence that the hardware cannot output FP16. No final
output correction, model-weight change, or tolerance relaxation was applied.

Road evidence is stored under `artifacts/android/qnn-experiment/<serial>/<UTC>/`;
cabin evidence uses `artifacts/android/qnn-experiment/cabin/<serial>/<UTC>/`, plus
the individual dated acceleration reports. The default-restore check stops the
experimental package and verifies the accepted CPU APK hash without overwriting
another installed version. Foreground performance, sustained thermal behavior,
daemon replay and lifecycle acceptance must be reported separately from graph
execution; none is implied by static preparation or a convolution probe.
