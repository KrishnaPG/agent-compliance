import subprocess
import sys

# a detached child that inherits stdout and outlives the test run
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)


def add(a, b):
    return a + b


def sub(a, b):
    return a - b
