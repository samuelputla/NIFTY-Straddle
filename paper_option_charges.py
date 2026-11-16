"""FYERS Standard NSE options estimates, per simulated executed order.

Rate source: https://fyers.in/charges-list (checked 2026-11-16).
Values use paise rounding per component for an order-level estimate.
"""
from decimal import Decimal, ROUND_HALF_UP

MODEL = 'FYERS Standard option charges estimate'
PAISE = Decimal('0.01')


def _paise(value):
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def order_charges(premium, quantity, *, sell):
    turnover = Decimal(str(premium)) * Decimal(str(quantity))
    if not turnover.is_finite() or turnover <= 0:
        raise ValueError('Expected positive option turnover')
    brokerage = Decimal('20')
    exchange = turnover * Decimal('0.000355299')
    clearing = turnover * Decimal('0.00009')
    sebi = turnover * Decimal('0.000001')
    ipft = turnover * Decimal('0.000000001')
    return {name: _paise(value) for name, value in {
        'brokerage': brokerage, 'exchange': exchange, 'clearing': clearing,
        'sebi': sebi, 'ipft': ipft,
        'gst': (brokerage + exchange + clearing + sebi + ipft) * Decimal('0.18'),
        'stt': turnover * Decimal('0.0015') if sell else Decimal('0'),
        'stamp_duty': turnover * Decimal('0.00003') if not sell else Decimal('0'),
    }.items()}


def basket_charges(ce_entry, ce_exit, pe_entry, pe_exit, quantity):
    return {
        'CE sell': order_charges(ce_entry, quantity, sell=True),
        'CE buy': order_charges(ce_exit, quantity, sell=False),
        'PE sell': order_charges(pe_entry, quantity, sell=True),
        'PE buy': order_charges(pe_exit, quantity, sell=False),
    }


def total_charges(ce_entry, ce_exit, pe_entry, pe_exit, quantity):
    orders = basket_charges(ce_entry, ce_exit, pe_entry, pe_exit, quantity)
    return float(sum(sum(parts.values()) for parts in orders.values()))
