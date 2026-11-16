"""Bounded retries for reads and writes to already reserved Sheet ranges."""
import time

from requests.exceptions import ConnectionError, Timeout


def retry_reserved_io(operation, delays=(2, 8, 22, 35)):
    """Retry only operations safe to repeat against the same range."""
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except Exception as error:
            response = getattr(error, 'response', None)
            status = getattr(response, 'status_code', None)
            transient = isinstance(error, (Timeout, ConnectionError)) or status in (
                429, 500, 502, 503, 504)
            if not transient or attempt == len(delays):
                raise
            delay = delays[attempt]
            print(f'Sheets transient error ({status or type(error).__name__}); retry in {delay}s',
                  flush=True)
            time.sleep(delay)
