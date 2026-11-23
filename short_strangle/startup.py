"""Bounded live startup; never substitute an old spot or a late entry."""
from contextlib import contextmanager
import json
import time

from quote_quality import quote_prices
from request_timing import run_with_timeout

INDEX = 'NSE:NIFTY50-INDEX'


class MarketDataError(RuntimeError):
    pass


def checked_response(method, response):
    if not isinstance(response, dict) or response.get('s') != 'ok':
        code = response.get('code') if isinstance(response, dict) else None
        # Do not print raw responses, payloads, tokens or provider messages.
        code = str(code) if isinstance(code, int) and not isinstance(code, bool) else 'unknown'
        raise MarketDataError(f'FYERS {method} failed (code {code})')
    return response


def capture_spot(call, fresh_spot, now, sleep=time.sleep):
    deadline = now().replace(hour=9, minute=30, second=20, microsecond=0)
    opened = deadline.replace(second=0)
    last_error = None
    while now() < deadline:
        if now() < opened:
            sleep(min(.2, (opened - now()).total_seconds()))
            continue
        spot = fresh_spot()
        if spot is not None and now() < deadline:
            return spot, now().isoformat()
        try:
            remaining = (deadline - now()).total_seconds()
            response = run_with_timeout(lambda: call('quotes', {'symbols': INDEX}), min(6, remaining))
            spot = quote_prices(response, [INDEX])[INDEX]
            if now() >= deadline:
                break
            return spot, now().isoformat()
        except Exception as error:
            last_error = error
            print('Spot capture retry:', str(error) if isinstance(error, MarketDataError) else type(error).__name__)
        sleep(max(0, min(1, (deadline - now()).total_seconds())))
    raise RuntimeError('Missed spot capture window after bounded retries') from last_error


@contextmanager
def reserved_session(store, output):
    try:
        yield
    except Exception as error:
        detail = str(error) if isinstance(error, MarketDataError) else type(error).__name__
        note = 'Collector failed: ' + detail + '; inspect workflow and saved evidence'
        try:
            (output / 'failure.json').write_text(json.dumps({'error': note}), encoding='utf-8')
        except OSError:
            print('Failure evidence file unavailable')
        if not store.saved:
            try:
                store.fail_startup(note)
            except Exception as write_error:
                print('Failure status write unavailable:', type(write_error).__name__)
        raise
