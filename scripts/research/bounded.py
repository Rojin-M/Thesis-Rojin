"""One owned subprocess, with a hard deadline even inside native library calls."""
import multiprocessing
import time


def _run(pipe, operation, args, kwargs):
    try:
        pipe.send((True, operation(*args, **kwargs)))
    except Exception as exc:
        pipe.send((False, {"type": type(exc).__name__, "message": str(exc)}))
    finally:
        pipe.close()


def bounded_call(operation, *args, seconds=300, heartbeat=None, **kwargs):
    if not 1 <= seconds <= 600:
        raise ValueError("Worker deadline must be 1–600 seconds")
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_run, args=(child, operation, args, kwargs), daemon=True)
    process.start()
    child.close()
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            if parent.poll(min(1., max(0., deadline - time.monotonic()))):
                try:
                    ok, result = parent.recv()
                except EOFError as exc:
                    raise RuntimeError("Owned worker exited without a result") from exc
                if not ok:
                    if result["type"] == "TimeoutError":
                        raise TimeoutError(result["message"])
                    if result["type"] in ("OSError", "FileNotFoundError", "PermissionError", "ConnectionError"):
                        raise OSError(result["type"] + ": " + result["message"])
                    raise RuntimeError(result["type"] + ": " + result["message"])
                return result
            if not process.is_alive():
                raise RuntimeError("Owned worker exited without a result")
            if heartbeat:
                heartbeat()
        raise TimeoutError("Owned worker reached its hard wall-clock limit")
    finally:
        parent.close()
        process.join(timeout=.1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
