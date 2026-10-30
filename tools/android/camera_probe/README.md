# Fold3 private camera probe

The root-free recipe and measured limitations are documented in [the investigation report](../../../docs/fold3-camera-investigation.md).

```powershell
python tools/android/camera_probe/build.py
adb -s <serial> install --no-incremental -r -g tools/android/.cache/camera-private/probe.apk
python tools/android/camera_probe/run.py --serial <serial> preview20-sustained
```

Builds only an on-phone Java/Dex application. No generated native host helper is built or run. `summarize.py` analyzes text evidence with standard-library Python. All scripts and imports are auditable in this directory.

The default package is unique and avoids installed Samsung apps. Alternative package names in earlier investigation were removed after testing. Never replace an installed app to run this diagnostic.

The launcher displays two live grayscale thumbnails for 60 seconds and closes capture. The successful session uses hidden logical ID 20, a genuine display preview, two YUV callbacks with Samsung stream roles, and a passive JPEG output. It omits standard physical-output bindings because the vendor HAL fails to return their required physical metadata.

`preview20-sustained` is the verified working case. Other cases intentionally reproduce unsupported configurations and can restart the vendor camera provider. The runner includes an ADB camera-service metadata preflight; standalone cold startup is not yet validated. The measured second stream is about 10 fps and is not ready for OpenPilot driving use.
