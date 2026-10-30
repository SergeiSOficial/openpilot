"""Build an on-device Java/Dex probe using installed Android SDK tools.

No generated program runs on the host; no NDK, host native compiler, FFI or JIT helper.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("Probe.java")
OUT = ROOT / "tools/android/.cache/camera-private"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default="com.samsung.android.openpilotprobe")
    args = parser.parse_args()
    if not all(part.isidentifier() for part in args.package.split(".")):
        raise ValueError("Invalid diagnostic package")
    sdk = Path(os.environ.get("ANDROID_HOME", Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk"))
    tools = sdk / "build-tools/36.0.0"
    android_jar = sdk / "platforms/android-36/android.jar"
    env = os.environ.copy()
    javac = Path(shutil.which("javac"))
    env["JAVA_HOME"] = str(javac.parent.parent)
    OUT.mkdir(parents=True, exist_ok=True)
    classes = OUT / "classes"
    dex = OUT / "dex"
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    for old_class in classes.rglob("*.class"):
        old_class.unlink()
    manifest = OUT / "AndroidManifest.xml"
    manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{args.package}">
<uses-sdk android:minSdkVersion="30" android:targetSdkVersion="35"/>
<uses-permission android:name="android.permission.CAMERA"/>
<application android:debuggable="true" android:label="Fold Camera Probe" android:theme="@android:style/Theme.Material.Light.NoActionBar">
<activity android:name="ai.comma.cameraprobe.Probe" android:exported="true">
<intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
</activity></application></manifest>''', encoding="utf-8")

    def run(*command):
        subprocess.run([str(x) for x in command], cwd=OUT, env=env, check=True,
                       shell=str(command[0]).endswith(".bat"))

    run(javac, "-source", "17", "-target", "17", "-classpath", android_jar, "-d", classes, SOURCE)
    run(tools / "d8.bat", "--lib", android_jar, "--output", dex, *classes.rglob("*.class"))
    run(tools / "aapt2.exe", "link", "-I", android_jar, "--manifest", manifest, "-o", OUT / "unsigned.apk")
    with zipfile.ZipFile(OUT / "unsigned.apk", "a") as apk:
        apk.write(dex / "classes.dex", "classes.dex")
    run(tools / "zipalign.exe", "-f", "4", OUT / "unsigned.apk", OUT / "aligned.apk")
    run(tools / "apksigner.bat", "sign", "--ks", Path.home() / ".android/debug.keystore",
        "--ks-pass", "pass:android", "--ks-key-alias", "androiddebugkey", "--out", OUT / "probe.apk", OUT / "aligned.apk")
    print(OUT / "probe.apk")


if __name__ == "__main__":
    main()
