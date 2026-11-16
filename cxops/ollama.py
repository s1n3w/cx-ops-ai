"""Start Ollama on demand and stop it when this process exits (adapted from Ask Data's launcher).

Ollama is started hidden inside a Windows job object set to kill everything in it when the job's
last handle closes. The handle belongs to this process, so Ollama and its model runner stop however
the program ends. If Ollama was already running, it is left alone.
"""
import contextlib
import ctypes
import os
import shutil
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

import requests

from . import llm

OLLAMA_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
STARTUP_TIMEOUT_S = 30
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kill_on_close_job(process: subprocess.Popen):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(wintypes.HANDLE(job), JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                          ctypes.byref(limits), ctypes.sizeof(limits))
    ok = ok and kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(process._handle))
    if not ok:
        raise OSError(ctypes.get_last_error(), "Couldn't attach Ollama to a job object")
    return job


def running() -> bool:
    try:
        return requests.get(f"{llm.OLLAMA_URL}/api/version", timeout=1).ok
    except requests.RequestException:
        return False


@contextlib.contextmanager
def ensure_running():
    """Context manager: starts Ollama if needed and stops it afterwards (only if we started it)."""
    if running():
        yield
        return
    exe = OLLAMA_EXE if OLLAMA_EXE.exists() else shutil.which("ollama")
    if not exe:
        raise SystemExit(f"Ollama isn't installed (expected it at {OLLAMA_EXE}).")
    process = subprocess.Popen([str(exe), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    job = _kill_on_close_job(process)  # noqa: F841 - must stay open while we run
    deadline = time.time() + STARTUP_TIMEOUT_S
    while not running():
        if process.poll() is not None or time.time() > deadline:
            process.kill()
            raise SystemExit("Ollama didn't start. Try running it once from the Start menu to see the error.")
        time.sleep(0.3)
    try:
        yield
    finally:
        process.terminate()
