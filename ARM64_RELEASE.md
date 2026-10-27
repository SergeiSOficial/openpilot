# Ioniq PHEV ARM64 release candidate

Built from `ioniq-phev-2018-stable` at
`8a7f2e73298a96888a715c367135cbeb2b3d4da0`, whose runtime base is openpilot
v0.11.2 (`6939d172e85e3b91f16d90cc8de72e8f938cc196`). No Hyundai control,
fingerprint, torque-limit, or safety implementation was changed.

The application and bindings were compiled for AArch64/cortex-a57 against the
verified AGNOS 19.9 SDK. Build orchestration ran in QEMU; native Clang 18.1.3
performed the cross compilation. All 18 packaged ELF files are AArch64.
Thirteen required artifacts pass dynamic-library resolution inside AGNOS.

ARM64 software validation: 241 passed, 194 skipped; the existing 2019 PHEV
route replay passed. The packaged bindings load and the compiled MPC solver
initializes inside the emulated deployment root. Stock SCC remains selected
with the existing 32 mph steering minimum. Keep alpha longitudinal and
experimental mode off for this profile.

Qualcomm GPU model files are reused upstream artifacts, not freshly executed
on hardware here. The driver-monitoring artifact comes from upstream commit
`de73842a2fedb82b4a0f8a3101189dde1b29ebf3`; its checkpoint, full metadata,
shapes, and tinygrad runtime match the validated source. Other device models
come from upstream release commit `f7db927c728bab57bb1263e05465766a8f28fc9d`.
The current official release's different driver-monitoring checkpoint was
rejected. Existing upstream panda firmware is unchanged and its release RSA
signatures were verified against the pinned public key; no debug firmware or
new signing key was substituted.

Camera, GPU, real CAN, onroad timing, installation, and 2018 vehicle acceptance
remain pending. This is an emulation-built candidate, not a hardware-approved
production release. Vehicle identification must succeed without forcing a
fingerprint before supervised acceptance testing.

See `build_manifest.json`, `SHA256SUMS`, and `build-evidence/` for exact
provenance and results. The bundled source guide retains its historical status
at the source commit; this file records the subsequent ARM64 packaging result.
