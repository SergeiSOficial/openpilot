# 2018 Ioniq PHEV: stable baseline and vehicle verification

Target: UK/Ireland right hand drive Hyundai Ioniq Plug-in Hybrid 2018 with factory
Smart Cruise Control (SCC) and lane keeping, connected to a comma four.

**Status: vehicle compatibility is unverified.** No firmware scan or route from
the target car was available when this branch was prepared. The existing 2019
PHEV platform is a candidate, not confirmation that the two model years match.
This branch changes no firmware fingerprints, control settings, or supported-year
claims. It prepares a reproducible stable baseline and the remaining checks.

## Pinned baseline

These pins were checked on 2026-10-27. They are intentionally fixed rather than
following development branches or future releases.

| Component | Reference | Commit |
| --- | --- | --- |
| openpilot source | `v0.11.2` | `6939d172e85e3b91f16d90cc8de72e8f938cc196` |
| comma four prebuilt deployment | `release-mici` | `f7db927c728bab57bb1263e05465766a8f28fc9d` |
| opendbc | source submodule | `b3bd79a659dae961af169a3baac723961f720133` |
| panda | source submodule | `a59195163c32a3a375ea6c86715dc08fd0984c1b` |

The local branch is `ioniq-phev-2018-stable`, based on the source commit above.
The other submodules retain the commits selected by that source tree. The
prebuilt release has a different tree and commit from the source tag; these
commits are not interchangeable. Its `git_src_commit` records
`a3a56b3aa4958ed9c45ed520c24b36bfe7cfa27c`, which also differs from the validated
source tag. Do not treat the official prebuilt as a build of this branch.
`release3` still points to v0.10.0 at the time
of this check and is not the comma four target.

The candidate is `HYUNDAI_IONIQ_PHEV_2019`, not `HYUNDAI_IONIQ_PHEV` (2020-22),
the regular hybrid, or the electric Ioniq. At the pinned opendbc revision:

| Setting | Existing 2019 PHEV value |
| --- | --- |
| Documented connector | Hyundai C; verify the actual car before connecting |
| Powertrain flag | `HYBRID` |
| Wheelbase / steering ratio | 2.7 m / 13.73 |
| Tire stiffness factor | 0.385 |
| Minimum steering speed | 32 mph = 51.5 km/h; retain the existing transition behavior |
| Controller torque maximum / rate up / rate down | 384 / 3 / 7, in controller units |
| Safety configuration with stock SCC | `hyundai`, `HYBRID_GAS`, without `LONG` |
| Longitudinal ownership | `pcmCruise=True`, `openpilotLongitudinalControl=False` |

The firmware database contains radar responses at `0x7d0`, EPS responses at
`0x7d4`, and camera responses at `0x7c4`. The 2019 camera entries are `AUS RHD`
and `USA LHD`, part number `95740-G2400`, date `180222`. There is no explicit
European RHD camera entry for this platform. Do not invent one from the model
year, a part number, or firmware observed on another car.

## First connection and evidence capture

1. Confirm that the car has SCC and lane keeping, and verify the Hyundai C
   connector fit and pinout against the actual camera/harness. Record the market,
   model year, trim, and ECU part labels. Matching connector shape alone is not
   sufficient evidence of electrical compatibility.
2. Install the official release through [openpilot.comma.ai](https://openpilot.comma.ai).
   This installer follows the current release. While parked, verify the installed
   version and commit; if it differs from the pinned deployment above, stop and
   review that release before treating it as this baseline. Do not install this
   source branch on the device for the initial capture.
3. Keep **enable openpilot** off for the initial recording. Keep **alpha
   longitudinal** (`AlphaLongitudinalEnabled`) and **experimental mode** off;
   alpha longitudinal is normally hidden on the release. Retain driver monitoring.
   Do not engage assistance during identification and data collection.
4. Record an ignition/startup session of at least two minutes while parked. Keep
   the complete `rlog.zst` segments, including segment 0, startup diagnostics, and
   any identification warnings. Normal startup performs diagnostic firmware
   queries; the recording itself must not inject custom CAN or steering commands.
5. Copy the logs before device cleanup removes them. Record the route name,
   installed commit, identification result, and relevant timestamps. A qlog alone
   is not sufficient for the CAN replay checks.

Use [the SSH instructions](connect-to-comma.md) with your own key. On the device,
these commands only inspect the installed checkout and available recordings:

```sh
git -C /data/openpilot rev-parse HEAD
find /data/media/0/realdata -maxdepth 2 -name 'rlog*' -print
```

Copy the actual segment paths using `scp`; for example, from a Linux workstation
after replacing both angle-bracket placeholders:

```sh
mkdir -p ~/ioniq-phev-2018-evidence
scp 'comma@<device-ip>:/data/media/0/realdata/<route>--0/rlog.zst' ~/ioniq-phev-2018-evidence/
```

For multiple segments, retain distinct filenames or their original directories.
Do not overwrite one segment with another. Keep startup firmware queries enabled;
do not set `FINGERPRINT`, `SKIP_FW_QUERY`, or manually substitute another model.

## Offline identification review

Use a Linux Python environment with the pinned opendbc and `zstandard` installed.
The following reads a local log, displays the recorded identification and firmware
bytes, and compares them with the database. It does not connect to the car, alter
the database, or approve compatibility:

```sh
python - /absolute/path/to/rlog.zst <<'PY'
import sys
from opendbc.car.logreader import LogReader
from opendbc.car.fw_versions import match_fw_to_car

cp = LogReader(sys.argv[1], only_union_types=True).first("carParams")
if cp is None:
    raise SystemExit("No carParams: retain the startup logs and investigate identification.")
for key in ("carFingerprint", "fingerprintSource", "fuzzyFingerprint", "pcmCruise",
            "openpilotLongitudinalControl", "minSteerSpeed", "flags"):
    print(f"{key}: {getattr(cp, key)}")
for fw in cp.carFw:
    print(f"{fw.ecu} address={fw.address:#x} subAddress={fw.subAddress} "
          f"bus={fw.bus} OBD={fw.obdMultiplexing} firmware={fw.fwVersion!r}")
exact, candidates = match_fw_to_car(cp.carFw, cp.carVin, log=False)
print("database matching:", ("exact" if exact else "fuzzy") if candidates else "no match")
print("database candidates:", sorted(candidates))
PY
```

Review all radar, EPS, and camera responses, firmware query provenance, and CAN
behavior. A fuzzy result or matching year label alone does not establish
equivalence. Confirm hybrid pedal and gear decoding, steering torque/angle,
wheel speeds, cruise state, and cancel/brake signals from the raw CAN.

If existing identification and CAN behavior are correct, retain the existing
platform unchanged. If the only verified gap is an observed firmware response,
add exactly those bytes under `HYUNDAI_IONIQ_PHEV_2019`, with matching and ambiguity
regression coverage. Keep the platform identifier and control limits unchanged.
Commit any justified opendbc change separately and pin that commit in openpilot;
do not leave a dependency on an uncommitted submodule edit. Extend documented
year/market coverage only after vehicle acceptance. Unknown or ambiguous results
remain unapproved; do not bypass identification to continue.

## Software validation

Run in Ubuntu 24.04 / Python 3.12, with an isolated environment. For firmware,
safety, and opendbc interface tests, a clean Linux export of the pinned opendbc
source is sufficient; a full driving-model download is not required.

From the opendbc directory with its dependencies installed:

```sh
python -m unittest -q \
  opendbc.car.hyundai.tests.test_hyundai \
  opendbc.car.tests.test_fw_fingerprint.TestFwFingerprint \
  opendbc.safety.tests.test_hyundai
python -m unittest -q \
  opendbc.car.tests.test_car_interfaces.TestCarInterfaces.test_car_interfaces_HYUNDAI_IONIQ_PHEV_2019 \
  opendbc.car.tests.test_car_interfaces.TestCarInterfaces.test_car_interfaces_HYUNDAI_IONIQ_PHEV
```

For route replay, use the upstream test case without forcing a car in the live
device. This standalone invocation tests the stored 2019 route with the pinned
opendbc interface and safety model and returns a failing exit code on failure:

```sh
python - <<'PY'
import unittest
from opendbc.car.hyundai.values import CAR
from opendbc.car.tests.routes import routes
from opendbc.car.tests.test_models import TestCarModelBase

route = next(r for r in routes if r.car_model == CAR.HYUNDAI_IONIQ_PHEV_2019)
case = type("TestIoniq2019Route", (TestCarModelBase,),
            {"platform": route.car_model, "test_route": route})
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(case))
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

After identification review, test a captured 2018 segment containing at least
50 seconds of CAN with the same `TestCarModelBase` checks. This invocation
requires the recorded platform to match and stock SCC to be selected; if that
gate fails, retain the logs and investigate rather than overriding it:

```sh
python - /absolute/path/to/rlog.zst <<'PY'
import sys
import unittest
from opendbc.car.hyundai.values import CAR
from opendbc.car.fingerprints import MIGRATION
from opendbc.car.logreader import LogReader
from opendbc.car.tests.routes import CarTestRoute
from opendbc.car.tests.test_models import TestCarModelBase

lr = LogReader(sys.argv[1], only_union_types=True, sort_by_time=True)
cp = lr.first("carParams")
if cp is None or MIGRATION.get(cp.carFingerprint, cp.carFingerprint) != CAR.HYUNDAI_IONIQ_PHEV_2019:
    raise SystemExit("Recorded identification requires review before replay acceptance.")
if cp.openpilotLongitudinalControl or not cp.pcmCruise:
    raise SystemExit("This recording is not the stock-SCC baseline.")

class TestIoniq2018Recording(TestCarModelBase):
    platform = CAR.HYUNDAI_IONIQ_PHEV_2019
    test_route = CarTestRoute("local-2018-recording", platform)

    @classmethod
    def get_testing_data(cls):
        return cls.get_testing_data_from_logreader(lr)

result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(TestIoniq2018Recording))
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

Offline evaluation does not authorize forcing a candidate on the car. Review
hybrid pedal/gear decoding directly as well as the automated CAN validity,
safety RX/TX agreement, cruise-state, and stock-SCC checks. Replay of a parked,
disengaged recording cannot establish engagement or driving behavior.

### Results recorded on 2026-10-27

| Check | Result |
| --- | --- |
| Source and all submodule pins | Match v0.11.2 |
| Hyundai tests, firmware fingerprint tests, Hyundai safety tests | 422 tests; OK, 194 skipped |
| 2019 and 2020-22 PHEV interface tests | 2 tests; OK |
| Stock-SCC parameters, exhaustive PHEV firmware combinations, unknown/ambiguous rejection without a CAN match | 4 local probes; OK, including all 108 firmware combinations across both PHEV generations |
| Existing 2019 route `3f29334d6134fcd4/2022-03-30--22-00-50` | 7 replay tests; OK |
| Runbook examples | Python syntax and local links checked; extraction and local replay exercised on the 2019 reference log |
| Target 2018 identification, CAN replay, and vehicle acceptance | Pending actual vehicle data |
| Full default openpilot build, including desktop tools and LLVM model compilation | Ubuntu 24.04 WSL2, x86_64, Python 3.12.13; `scons -j4` succeeded |
| LFS asset integrity | All 262 pinned objects pass `git lfs fsck --objects HEAD` in both checkouts |
| Checks in the built, locked environment | Compiled bindings import; 422 Hyundai/firmware/safety tests (194 skipped); 2 openpilot PHEV interface tests; C++ logging smoke test: all passed |
| Incremental build review | Dry run succeeds; only the deliberately always-built `compile_commands.json` is scheduled |
| comma four ARM64 build / deployment and vehicle acceptance | Not performed |

The initial software checks used the unmodified pinned opendbc source exported to
a native WSL Linux directory. The full build and subsequent checks used the
complete pinned openpilot tree with its frozen dependency lock. These results do
not establish support for the target 2018 car.

The reference route is a legacy recording: its recorded parameter defaults and
firmware metadata predate this baseline. Its raw CAN passes the pinned interface
and safety replay, but its recorded parameters are not evidence of the current
configuration. Use a fresh v0.11.2 recording for the target car's identification.

### Full host build and recovered downloads

The native Linux build checkout is `/home/dey/openpilot-ioniq-stable` in the
`Ubuntu-24.04` WSL distribution, on branch `ioniq-phev-2018-stable`. It preserves
Linux symlinks and reuses the original Windows clone's Git and LFS caches. Keep
that original clone available. Source and all submodules remain at the pinned
revisions; only the documentation changes accompany the build. Concurrent edits
to the Windows checkout's branch, `pandad`, and dependency files were preserved
and are outside this build's validated source tree.

The interrupted model download failed during DNS lookup for `huggingface.co`.
Recovery used the canonical Hugging Face LFS batch endpoint and a resumed HTTPS
download, without replacing the endpoint or weakening TLS verification. The
799,950,476-byte `big_driving_tinygrad.pkl` was resumed from 658,314,017 bytes and
checked against SHA-256
`b3864072b1cf3c662d7f293fd16aab7318f2717388c3ddb721f5d57474acde6b`.
All five model assets and all 262 pinned LFS objects are now hydrated and
verified. Ordinary `git lfs pull` also completes successfully in the Windows
checkout.

Both checkouts use repository-local LFS settings to bound future stalls:
`lfs.concurrenttransfers=2`, `lfs.dialtimeout=20`, `lfs.tlstimeout=20`,
`lfs.activitytimeout=60`, and `lfs.transfer.maxretries=3`. These do not change
system DNS or other repositories.

To build again from PowerShell, with the installed Linux environment:

```powershell
wsl -d Ubuntu-24.04 --cd /home/dey/openpilot-ioniq-stable --exec env PWD=/home/dey/openpilot-ioniq-stable bash -c 'source .venv/bin/activate && scons -j4'
```

Build and validation evidence is retained in
`/home/dey/.cache/ioniq-phev-2018/`: `full-build-initial.log`, `full-build.log`,
`full-build-result.json`, `built-check-results.json`, and the corresponding
`built-*.log` files. The recorded full build exited 0. It builds the default
Linux host targets, including replay, Cabana, Jotpluggler, compiled bindings,
tests, and the CPU/LLVM model artifacts. It does not produce or validate a
comma four ARM64 release image.

The incremental dry run confirms that compiled targets are current. `scons -q`
returns 1 because the upstream compilation-database builder deliberately marks
`compile_commands.json` with `AlwaysBuild`; this is not a failed compiler target.

### Comma four ARM64 release prerequisites

An ARM64 release has not been built or published from this source branch. The
available WSL builder is x86_64, has no AGNOS installation or configured comma
four target, and has no production release-signing asset. The GitHub workflow
named `build_release` also uses an amd64 host; its name does not establish a
comma four build.

The stock `tools/release/build_release.sh` requires an ARM64 AGNOS build/test
device, the target-specific runtime and GPU/model compilation environment,
release signing at `/data/pandaextra/certs/release`, and the device
`test_onroad.py` gate. Do not substitute host binaries, spoof `/AGNOS`, skip
device tests, or silently switch to debug firmware to label a host build as a
device release.

Use a dedicated build device and a source checkout outside `/data/openpilot`:
the stock script recreates that directory and force-pushes its configured
destination. Preserve any existing device installation before using that
pipeline. A custom prebuilt destination should be a distinct branch such as
`ioniq-phev-2018-release-mici`, not an existing upstream or fork release branch.
Target access and signing setup are required before that pipeline can be run.

### Extended WSL validation

A subsequent validation run on the same pinned Linux checkout completed with
**361 tests passed and 194 skipped**, plus the following asset and runtime checks:

| Area | Result |
| --- | --- |
| Parameters, file helpers, Kalman filter, Markdown, controllers, and cruise simulations | 63 passed |
| All Hyundai openpilot interfaces | 36 passed |
| Hyundai configuration, firmware matching, and safety | 422 reported; 228 passed, 194 skipped |
| Messaging, polling, and fake socket events | 23 passed |
| Stock-SCC baseline and identification rejection probes | 4 passed, including all 108 recorded PHEV firmware combinations |
| Recorded 2019 PHEV route replay | 7 passed |
| Compiled driving and driver-monitoring CPU/LLVM models | 3 inferences each; finite, repeatable outputs that change with input |
| Compiled C++ logging test | Exit 0 |
| Pinned LFS assets | Integrity check passed |

The messaging run initially failed because the validation harness had not
created its isolated shared-memory directory. Rerunning that suite with the
upstream `OpenpilotPrefix` fixture passed all 23 tests; no production-code
change was needed. The initial failure log is retained alongside the successful
rerun. Other passing suites were not repeated.

The full report and per-suite logs are in
`/home/dey/.cache/ioniq-phev-2018/wsl-validation/`, also copied to the Windows
checkout's `.git/ioniq-validation/wsl-validation/`. These checks validate host
software behavior and serialization/inference, not model accuracy or the target
2018 vehicle's compatibility.

## Acceptance and rollback

Only after reviewing the target car's identification and CAN evidence, complete
supervised vehicle checks in a controlled setting: engage above the existing
steering minimum, verify cancel and brake disengagement, driver steering
override, low-speed steering alerts/transitions, stock SCC ownership, and absence
of persistent faults. Do not lower the steering minimum to obtain low-speed
steering. Do not test AEB by deliberately approaching an obstacle.

Record installed commits, routes/timestamps, conditions, and pass/fail findings.
No custom firmware or tuning is accepted until those checks pass. Future tuning
requires measured before/after behavior and a separate change.

If identification is wrong or faults occur, remain disengaged, park, and turn
**enable openpilot** off. Revert any future custom installation using the
device's uninstall/setup flow and the official installer above; verify the
installed release again. For persistent vehicle faults, power down and restore
the original camera connection using the harness installation procedure before
relying on stock assistance. Preserve the failure logs.

For local source rollback, preserve local edits first, then switch branches and
restore their recorded submodules:

```sh
git switch master
git submodule update --init --recursive
```

This local branch switch does not change software installed on the comma four.
