# Fold3 accelerator repair evidence

The original road and cabin models are preserved. Original-model checks use
`rtol=1e-4`, `atol=1e-5`; byte preprocessing and image history remain exact.
Numerical agreement, actual accelerator execution, and sustained performance
are separate results. No result here enables vehicle actuation or live road
selection.

## Road arithmetic diagnosis

The diagnostic captures complete logical input views before each retained
kernel, including byte offsets and overlapping aliases. It records the first
bit difference separately from the first tolerance failure. Teacher-forced
kernel replays restore the original free-running inputs and outputs afterward.
Captures are bounded and contain synthetic zero-model tensors, not live pixels.

On the physical Fold3, the first bit difference was kernel 69 (`r_256_4_32`),
with byte-identical complete inputs. Output 374 was `-8.33272933959961e-05`
on packaged CPU versus `-8.32676887512207e-05` on CL. Kernel 72 subsequently
failed tolerance, but its complete-input replay was bit-exact. Its row 416
FP32 accumulator matched both packaged CPU and the reviewed scalar oracle:
`0.026801861822605133`. Half rounding before bias produced
`0.1923828125`, as expected. Thus kernel 72 inherited the earlier discrepancy.

Evidence: `artifacts/android/live/67e8f2b0766b428d/verification.json` and
`artifacts/android/gpu-repair/67e8f2b0766b428d/`.

Adreno reports that correctly rounded FP32 divide/sqrt is unavailable. A
32-bit restoring divider preserves IEEE round-to-nearest-even, signed zero,
subnormals and exceptional inputs. It fixes the captured normalization
regression without model or output changes. A 64-bit division implementation
was rejected after a vendor-driver abort; it is not retained.

With the 32-bit divider, the original road zero-input model and random exact
camera-warp gates passed on the Fold3:
`artifacts/android/live/431f375784274148/verification.json`. This is a narrow
numerical result. A subsequent isolated 60-frame GPU attempt aborted inside
Adreno `cl_a6x_cmdbuf_mgr_submit_ibs`; that attempt did not pass a sequence or
performance gate. Its original CPU reference passed 60 frames (mean 191.3 ms):
`artifacts/android/acceleration/RFCR81Y1TBJ/20261029T141134Z/`.

## Recurrent storage diagnosis

A physical 60-frame check reached frame 4 with all raw outputs accepted, then
rejected 393,216 history bytes. Complete incoming CPU captures showed the same
first three states as the independent GPU sequence. The physical CPU's oldest
history plane unexpectedly duplicated its next plane on frame 4; the original
ONNX/emulator corpus kept that oldest plane zero until frame 5. These corpora
are retained separately and must not be interchanged silently.

A synthetic nonzero-history replay isolated kernel 3 (`E_2_196608_5`) with
byte-identical complete inputs and the same input/output aliasing: packaged
ARM CPU returned 48 where the source's load-before-store sequence and CL
returned 32. Its generated C declared both aliased arguments `restrict`.
The Android CMake target now removes that invalid pointer promise with the
`restrict=` definition, retaining the original operators, source arithmetic,
model weights and tolerances. Both Android ABIs were cross-built; old native
library/corpus evidence does not qualify these new identities. No host-native
helper was rebuilt or executed.

Evidence: `artifacts/android/gpu-repair/road-state-20261030/`, including the
verified original physical capture hashes, CPU/CL kernel sources and first
identical-input discrepancy. After the correction, the physical synthetic nonzero-history replay matched
all 159 kernels bit-for-bit, with no first bit difference. The original and
corrected reports and installed-APK/native/source identities are retained in
that directory. The fresh 60-frame CPU reference also passed
(`artifacts/android/acceleration/RFCR81Y1TBJ/20261030T095626Z/`); its p95 was
193.27 ms and is diagnostic only. GPU sequence and replay gates remain separate.

## Cabin diagnosis

The original 553-output Android ORT CPU reference remains authoritative.
Direct ONNX CL execution fails its zero-input check. Diagnostics also export
ORT's mandatory CPU lowering with `NO_OPT`, leaving the original file intact.
The diagnostic graph must reproduce all original CPU outputs before its
intermediates can be used. The first 24 dynamic activations pass tolerance;
this does not qualify the complete cabin GPU model.

Evidence: `artifacts/android/live/8a7fc9ad4ee94a16/verification.json`.
The first native-half depthwise convolution's 90,000 outputs were made
bit-exact by matching ORT's bias-first half-FMA accumulation. An identical-input
pointwise capture identifies the same arithmetic requirement. The candidate
also follows ORT 1.23.2's `(kH,kW,C/group)` half-GEMM reduction order. The pinned
[ORT FP16 convolution source](https://github.com/microsoft/onnxruntime/blob/v1.23.2/onnxruntime/core/providers/cpu/fp16/fp16_conv.cc)
documents its NHWC input/filter conversion. A complete-input FP32 convolution
replay passed while free graph execution diverged; an explicitly materialized
CL-node candidate now isolates graph fusion/storage lifetimes. Explicit CL-node materialization reduced the full zero-input error from
2.8671875 to 0.0048828125, with 479/553 outputs still outside tolerance. The
first 32 diagnostic activations pass tolerance. These results reject cabin
GPU selection and do not qualify the complete model. Evidence:
`artifacts/android/live/ef813ce945f14736/`.

Evidence: `artifacts/android/live/377c98c0141346f8/`,
`5c53a369d44c4fce/` and `ecb30e7861174ce8/`.

The regular Cabin Diagnostic retains its accepted explicit CPU path until
the full original-model numerical checks pass. Monitoring validity remains
subject to its independent geometry, calibration, freshness and cadence gates.

## Validation boundaries

`tools/android/tests/test_gpu_diagnostic.py` uses only Python's standard library
for complete-capture integrity, bounds, aliases, half rounding, float division
and captured scalar arithmetic. Model execution and native tests run only on
Android. `prepare_cabin_gpu_diagnostic.py` performs static ONNX graph inspection,
with no host model execution. The isolated quantized road/cabin workflow and
its separate original-model, quantized-reference and HTP-provider gates are
documented in [android-qnn-quantized.md](android-qnn-quantized.md).

The repaired zero-input check does not replace the 60-frame recurrent test,
actual provider evidence, lifecycle/replay checks, or 20-minute foreground run.
No 20 Hz road qualification has been issued. Camera cadence and thermal limits
remain independent blockers.

## Latest integration status (30 October 2026)

The road GPU completes the physical Fold3 60-frame independent recurrent
comparison with **zero raw-output error**, 180 state checks, 60 exact history
checks and exact preprocessing. The latest unlocked foreground cycle mean is
174.94 ms and p95 is **176.68 ms**; including parsing, p95 is177.57 ms. All60
cycles exceed50 ms, so live road remains blocked. `timing_qualified` in the
benchmark JSON means foreground measurement only, never a sustained20 Hz pass.
Evidence: `artifacts/android/acceleration/RFCR81Y1TBJ/20261030T151723Z/`.
The measured APK b7bbadf2… and its test APK are retained under
`artifacts/android/gpu-repair/road-numerical-20261030/apks/`.

The earlier numerically repaired lowering took15630.94 ms at p95. Address
analysis now recognizes masked padding reads and worker-owned residues in
aliased history buffers; independent axes are flattened bijectively in output
stride order, with complete workgroups and no padded/duplicate work. These are
scheduling/storage-ownership proofs; floating arithmetic is unchanged. All six
native diagnostics pass with fresh processes and cleanup between cases. Both
159-kernel identical-input comparisons remain bit-exact. The separate device
trace falls from12641.52 ms to167.48 ms. A first convolution still costs41.59 ms,
a conservatively serial convolution32.15 ms and a small poorly occupied head
15.01 ms. These are measured blockers in the retained exact lowering, not proof
of an absolute hardware ceiling.

The repaired CPU history copy and restoring-integer FP32 division/square root
preserve the original model's arithmetic, subnormals and recurrent aliasing.
The first frame-36 square-root discrepancy is resolved. No numerical tolerance,
original model weight, image/history contract or live qualification threshold
has been relaxed.

Cabin's pinned MLAS contracted tanh and twelve measured FP32 convolutions are
integrated. Their complete-input arithmetic proofs pass, including all450720
outputs from the nine additional pointwise nodes. The latest whole-model zero
check still rejects419/553 values (maximum error0.001708984375); its first selected
bit difference is FP32 depthwise Conv819. A subsequent physical probe proves
zero-initialized sequential FMA followed by bias matches all619968 outputs of
all eleven depthwise nodes exactly; bias-first and separate multiply/add do not.
That repair is pending integration/full-model validation. Cabin Diagnostic
continues using its original CPU provider until all numerical/selection gates
pass. No live camera pixels have been persisted.

Native packing, bounded ownership, sensor cleanup and the60-frame/12-daemon
replay pass their four Android tests; the affected lifecycle suite passes13
checks. Those reports retain the APK identities actually tested. They do not
certify a later backend or a20-minute accelerator run.

The isolated road QNN candidate executes60 teacher-forced and60 independent
frames on physical V68 HTP with CPU fallback disabled and provider traces. It
fails numerical agreement: maximum error34.93 against the quantized reference,
35.57 against the original. Its approximately21 ms execution-only p95 excludes
the complete pipeline. Normalization codes match; the following convolution's
quantized codes do not. Cabin's FP16 output-boundary probe also fails strict
agreement, leaving full-model cabin HTP blocked. See
[android-qnn-quantized.md](android-qnn-quantized.md) for separate role, calibration,
runtime, native-library, provider and APK evidence. Quantized candidates remain
outside the default live pipeline.

## Experiment memory and interrupted runs

Before and after each experiment, the reviewed host helper force-stops only the
three project experiment packages, verifies that their main/worker PIDs exit,
and retains bounded package PSS, MemAvailable, swap and thermal readings. It
never drops system caches or terminates unrelated apps. A failed evidence read
still attempts the approved package stops and prevents the next experiment.
The initial post-reboot check records no remaining experiment processes and
4982200 KiB available memory at thermal status0. Memory readings describe the
system; they do not prove per-allocation GPU/driver reclamation.

Primary candidate results and attempt IDs are saved before optional logcat
collection. USB timeouts retain partial text and an incomplete result; stale or
partial JSON cannot pass. `test_acceleration.py --frames 3 --backends gpu` is a
short diagnostic and never satisfies the 60-frame gate. Actual APK, retained
artifact, loaded runtime and native-library identities are now required by the
road certificate validator; old or incomplete identities are rejected. The gate change is included in the rebuilt main app and passes host/captured-identity checks; no live certificate has been issued.
