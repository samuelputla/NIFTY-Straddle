import ast,sys
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parent if Path(__file__).with_name("expiry_metrics.py").exists() else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from expiry_metrics import calendar_dte,choose_monthly_date

assert calendar_dte('2026-10-19','19-10-2026')==0
assert calendar_dte('2026-10-16','19-10-2026')==3
assert calendar_dte('2026-10-23','03-11-2026')==11
try:calendar_dte('2026-10-20','19-10-2026');raise AssertionError()
except ValueError:pass
oct27=date(2026,10,27);nov23=date(2026,11,23);weekly=date(2026,11,3)
assert choose_monthly_date(date(2026,10,26),[oct27,weekly,nov23],[oct27,nov23],[oct27,weekly,nov23])==oct27
assert choose_monthly_date(oct27,[oct27,weekly,nov23],[oct27,nov23],[oct27,weekly,nov23])==oct27
assert choose_monthly_date(date(2026,10,28),[weekly,nov23],[oct27,nov23],[weekly,nov23])==nov23
try:choose_monthly_date(date(2026,10,26),[weekly],[oct27],[oct27]);raise AssertionError()
except ValueError:pass
for name in (['core.py','next.py','monthly_expiry_straddle.py'] if (ROOT/'core.py').exists() else ['today_test.py','next_expiry_straddle.py','monthly_expiry_straddle.py']):
    tree=ast.parse((ROOT/name).read_text(encoding='utf-8'));env={}
    wanted={'LEGACY_SL_PERCENTAGES','EXTRA_SL_PERCENTAGES','SL_PERCENTAGES','CONTRACT_QTY','ROUND_TRIP_CHARGES_RUPEES','DAILY_HEADERS','SCENARIO_HEADERS'}
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in wanted for t in node.targets) or isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id in wanted:
            exec(compile(ast.Module(body=[node],type_ignores=[]),name,'exec'),env)
    assert len(env['DAILY_HEADERS'])==83 and len(env['SCENARIO_HEADERS'])==31
    assert env['DAILY_HEADERS'][-1]==env['SCENARIO_HEADERS'][-1]=='DTE'
    assert env['CONTRACT_QTY']==65 and env['ROUND_TRIP_CHARGES_RUPEES']==150
    assert env['SL_PERCENTAGES']==[10,15,20,25,30,35,40,45,50]
print('PASS: calendar DTE, expiry-day zero, holiday/weekend span, monthly roll, fail-closed metadata, all three schemas and unchanged risk constants')
