#!/usr/bin/env python3
"""Check a packaged FluidWorx: its self-test passes, and its window opens an example and stays open."""
import os
import subprocess
import sys
import tempfile
import time


def main(exe, example):
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, FLUIDWORX_CONFIG_DIR=d)
        report = os.path.join(d, "report.txt")
        code = subprocess.run([exe, "--self-test", report], env=env, timeout=120, check=False).returncode
        text = open(report, encoding="utf-8").read() if os.path.exists(report) else ""
        print(text)
        if code != 0 or "PASSED" not in text:
            print("self-test failed")
            return 1
        p = subprocess.Popen([exe, example], env=env)
        time.sleep(10)
        if p.poll() is not None:
            print(f"the window closed by itself with code {p.returncode}")
            return 1
        p.terminate()
        p.wait(timeout=30)
    print("packaged check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
