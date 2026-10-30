# Fold 3 performance compared with comma hardware

Checked 2026-10-28. The current Android port is below openpilot's real-time target.
Its measured model cycle averages **246–250 ms**, against a **50 ms / 20 Hz** budget.
The original comma four recording averages **27.6 ms**. The measured configuration
gap is approximately **9×**, including differences in model and software versions.

## Which hardware is current

The latest standalone device is **comma four**, using Snapdragon 845 MAX. Its MAX
cooling is designed for sustained operation. The optional **chestnut** upgrade
adds an AMD Radeon RX 9060 8 GB. These are different compute configurations.
Sources: [comma four specifications](https://comma.ai/shop/comma-four),
[comma four introduction](https://blog.comma.ai/comma-four/),
[chestnut specifications](https://comma.ai/shop/chestnut).

The connected Fold 3 reports `SM8350` / `lahaina` (Snapdragon 888, also listed in
[Samsung's device chipset table](https://www.commoncriteriaportal.org/nfs/ccpfiles/files/epfiles/st_vid11664-st.pdf)). This port runs
the driving model and image warp through packaged **CPU:CLANG** kernels. The
current comma-device implementation selects **QCOM** for the small model and
**USB+AMD:LLVM** for chestnut. See [model backend selection](../openpilot/selfdrive/modeld/helpers.py)
and [Android environment](../android/app/src/main/python/android_runtime/worker.py).

## Measurements already captured on the devices

| Metric | Recorded comma four | Fold 3 landscape run | Second verified Fold 3 run |
|---|---:|---:|---:|
| Model samples | 60 | 60 | 60 |
| Mean model cycle | 27.57 ms | 246.06 ms | 250.36 ms |
| Median | 27.68 ms | 244.36 ms | 205.44 ms |
| 95th percentile | 29.76 ms | 310.61 ms | 415.79 ms |
| Worst cycle | 30.26 ms | 404.86 ms | 460.09 ms |
| Cycles over the 50 ms budget | 0/60 | 60/60 | 60/60 |
| Mean after excluding the first cycle | 27.56 ms | 243.37 ms | 246.81 ms |
| Replay backend elapsed, including daemon startup and verification | Not measured | 26.21 s | 29.25 s |
| Full-job frame pairs per elapsed second | Not measured | 2.29 | 2.05 |

The model-cycle timer surrounds `ModelState.run`: input transfer, both camera
warps, model execution, output transfer and parsing. It excludes daemon/model
initialization before the loop. All 120 measured phone cycles exceed 50 ms,
including after the first cycle, so startup alone does not explain the gap.
See the timer in [modeld](../openpilot/selfdrive/modeld/modeld.py).

The source's model rate is **20 Hz**, and its control loop uses a **10 ms / 100 Hz**
step. The simulation preserves recorded virtual timing while running slowly;
timestamps spaced 50 ms apart in Android output do not establish 20 Hz wall-clock
performance. See [model constants](../openpilot/selfdrive/modeld/constants.py),
[loop timing](../openpilot/common/realtime.py) and
[upstream model constants](https://github.com/commaai/openpilot/blob/master/openpilot/selfdrive/modeld/constants.py).

In the landscape run, model cycles total **14.76 seconds**, or **56.3%** of the
26.21-second replay interval. The remainder includes worker startup, IPC,
other daemons, integrity checks and reference comparison. This timer starts inside
the replay backend, after the replay service has extracted its initial assets and
started Python; it is not an app cold-start benchmark.

## Comparison limits

The public fixture's `initData` identifies `deviceType=7` (`mici`, comma four),
openpilot **0.10.2**, branch `nightly-dev`, commit
`d390bff2b4c75bae347dd65f23dcc857439bad6a`. Its 60 model records have `big=false`.
The port uses openpilot **0.11.2**, standard `driving_supercombo.onnx`, SHA-256
`65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce`.
The recording does not establish that these are identical model weights.
Consequently, **9× is a comparison of observed configurations, not an isolated
Snapdragon 888 versus Snapdragon 845 hardware speed ratio**.

Both phone runs passed all existing numerical comparisons against the same-source
desktop reference. That establishes correctness for this fixture. Live road
cameras, driver-monitoring model inference, physical vehicle I/O and sustained
thermal behavior are outside this APK's measured workload. No comma four was
connected for a new same-model benchmark.

The newest chestnut-class model in openpilot 0.11.2 has **382.9 million parameters**
and **93.46 GFLOPs**, versus **26.6 million / 1.687 GFLOPs** for the 0.11.1 small
model in comma's published table: approximately **55× more computation**. This is
a workload comparison, not a measured latency multiplier. This APK has not run
that big model. Source: [openpilot 0.11.2 release](https://blog.comma.ai/0112release/).

## Practical implication

The current CPU path needs approximately **5× lower mean model-cycle time**, and
**6–8× lower p95 time**, to fit a 50 ms model budget; other runtime work still
needs headroom. An Android-accessible GPU inference path and a sustained,
same-model on-target benchmark are the next useful performance steps. A newer
phone SoC alone does not establish performance parity with comma's accelerated
deployment.

## Evidence and reproduction

- [Raw timing samples and statistics](../artifacts/android/fold3/performance.json)
- [Landscape replay](../artifacts/android/fold3/d8ffcf8fb9a24397/verification.json)
- [Second replay](../artifacts/android/fold3/8b9b5a45672b4e15/verification.json)
- [Pure Python decoder](../tools/android/performance_report.py)

```powershell
py -3.12 tools/android/performance_report.py --session d8ffcf8fb9a24397 --additional-session 8b9b5a45672b4e15
```

This reads existing unpacked logs and the generated schema header as data. It uses
only Python's standard library; it does not import capnp/NumPy, compile or load
native helpers, or run a new device test. Header offsets, input hashes, source
identities and per-frame samples are recorded in the JSON. The public route is
`98395b7c5b27882e|0000002b--2686b5a2d0`, segment 1; source URLs and hashes are pinned
in [fixture sources](../tools/android/fixture.sources.json).
