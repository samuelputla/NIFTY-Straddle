"""Pure, offline-testable rules for the isolated weekly paper strategy."""
import math


def valid_price(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def inward_strike(side, old_strike, new_strike, retained_strike):
    """Move toward, or onto, the retained strike; never cross it."""
    if any(v is None for v in (old_strike, new_strike, retained_strike)):
        return False
    old, new, retained = map(float, (old_strike, new_strike, retained_strike))
    return old < new <= retained if side == 'PE' else old > new >= retained


def fresh_pair(symbols, prices, timestamps, now, max_age=5, max_skew=2):
    stamps = [timestamps.get(symbol) for symbol in symbols]
    return (all(valid_price(prices.get(symbol)) for symbol in symbols)
            and all(t is not None and 0 <= (now-t).total_seconds() <= max_age for t in stamps)
            and (max(stamps)-min(stamps)).total_seconds() <= max_skew)


def replacement_valid(low_side, low_leg, high_leg, new_strike, new_price,
                      low_price, high_price, threshold, profitable_only):
    if not all(valid_price(p) for p in (new_price, low_price, high_price)):
        return False
    return (high_price > low_price
            and (high_price-low_price)/high_price >= threshold
            and (not profitable_only or low_price < float(low_leg['credit']))
            and inward_strike(low_side, low_leg.get('strike'), new_strike, high_leg.get('strike'))
            and high_price*.90 <= new_price <= high_price*.95)


def execution_cost(action, premium, quantity, profile):
    """User's all-in flat estimate per leg execution, not a broker tariff."""
    if action not in ('SELL TO OPEN', 'BUY TO CLOSE'):
        raise ValueError('Unknown execution action')
    return float(profile['cost_per_execution'])
