"""Deadline helpers: timed-out SDK workers must not hold up the main process."""
import threading
import time


def start_request(function, *args):
    outcome = {}
    completed = threading.Event()

    def request():
        try:
            outcome['value'] = function(*args)
            outcome['received_at'] = time.monotonic()
        except Exception as exc:
            outcome['error'] = exc
        finally:
            completed.set()

    threading.Thread(target=request, daemon=True, name='bounded-api-request').start()
    return completed, outcome


def await_request(pending, timeout_seconds):
    completed, outcome = pending
    if not completed.wait(max(0, timeout_seconds)):
        raise TimeoutError('API request exceeded its deadline')
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']


def run_with_timeout(function, timeout_seconds, *args):
    return await_request(start_request(function, *args), timeout_seconds)


def collect_ready_requests(pending, expired=False):
    """Poll optional requests without waiting for unfinished workers."""
    results = {}
    for name, request in list(pending.items()):
        if not request[0].is_set():
            if expired:
                results[name] = (None, TimeoutError('Metadata deadline exceeded'))
                del pending[name]
            continue
        try:
            results[name] = (await_request(request, 0), None)
        except Exception as exc:
            results[name] = (None, exc)
        del pending[name]
    return results

