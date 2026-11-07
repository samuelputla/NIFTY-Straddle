"""Single workflow writer, fixed-cell idempotent writes and sealed call records."""
import json
from .engine import digest,validate_plan,stamp

BOOK='1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
CALLS='Short Term Calls'
STATUS='Short Term Status'
EVENTS='Short Term Events'
RUNS='Short Term Runs'
PORTFOLIO='Short Term Portfolio'
SCHEMAS={
 CALLS:['Call ID','Symbol','Type','Issued At','Start At','Enter By','Exit By','Observe Until',
        'Trigger','Entry Min','Entry Max','Stop','Target 1','Target 2','Quantity','Total Costs',
        'Exit Policy','Source','Rationale','Limitations','Plan Hash','Plan JSON','Registered At','Paper Selection'],
 STATUS:['Call ID','Symbol','Type','Status','Breakout At','Retest Observed','Confirmation At',
         'Paper Entry At','Paper Entry','Exit At','Exit Price','Exit Reason','Gross Per Share',
         'Gross P&L','Net P&L','Observed MFE Per Share','Observed MAE Per Share','Missed Targets',
         'Post Exit Touches','Missing Minutes','As Of','Method','Evidence Hash',
         'Gross Return %','Estimated Costs','Net Return %','Quantity','Last Price','Last Minute',
         'Planned T1 R','Planned T2 R','Realized R'],
 EVENTS:['Event ID','Call ID','Event','Observed Minute IST','Price','Detail'],
 RUNS:['Run ID','As Of','Stage','Status','Call Count','Detail','Workflow URL','Version'],
 PORTFOLIO:['Account','Initial Capital','Realized Gross','Gross ROI %','Unrealized Gross',
            'Deployed Capital','Reserved Capital','Available Cash','Selected Calls','Review Calls','As Of','Cost Assumption']}


def row_for_plan(p,now):
    return [p[k] if p.get(k) is not None else '' for k in
        ('id','symbol','type','issued_at','start_at','enter_by','exit_by','observe_until','trigger',
         'entry_min','entry_max','stop','target_1','target_2','quantity','total_costs','policy','source','rationale')]+[
        p.get('limitations',''),digest(p),json.dumps(p,sort_keys=True),now,bool(p.get('portfolio_selected',False))]


class Store:
    def __init__(self,book):
        from sheets_resilience import RollingSheetStore
        self.book=book
        titles={s.title for s in book.worksheets()}
        for title,headers in SCHEMAS.items():
            if title not in titles:
                sheet=book.add_worksheet(title,20000 if title==EVENTS else 5000,len(headers))
                sheet.freeze(rows=1,cols=1)
        class RawValuesBook:
            def values_batch_get(self,ranges):
                return book.values_batch_get(ranges,params={'valueRenderOption':'UNFORMATTED_VALUE'})
            def values_batch_update(self,body):return book.values_batch_update(body)
        self.cache=RollingSheetStore(RawValuesBook(),SCHEMAS)
        for title in SCHEMAS:
            ids=[r[0] for r in self.cache.snapshot(title)[1:] if r and r[0]]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate records: '+title)

    def plans(self):
        plans=[]
        for row in self.cache.snapshot(CALLS)[1:]:
            if not row or not row[0]:continue
            if len(row)<23:raise ValueError('Incomplete frozen call')
            p=json.loads(row[21]);validate_plan(p)
            if digest(p)!=row[20] or p['id']!=row[0]:raise ValueError('Frozen plan changed')
            if len(row)>=24 and str(row[23]).lower()!=str(bool(p.get('portfolio_selected',False))).lower():
                raise ValueError('Visible paper selection changed')
            # Visible original fields must still agree with their sealed JSON.
            expected=row_for_plan(p,row[22])
            from .engine import number
            for i,(a,b) in enumerate(zip(row[:21],expected[:21])):
                same=(number(a)==number(b)) if 8<=i<=15 and a!='' and b!='' else str(a)==str(b)
                if not same:raise ValueError('Visible original call changed')
            plans.append(p)
        return plans

    def register(self,p,now):
        validate_plan(p)
        existing={x['id']:x for x in self.plans()}
        if p['id'] in existing:
            if digest(p)!=digest(existing[p['id']]):raise ValueError('Call ID cannot be rewritten')
            return
        if p.get('status','Active')=='Active' and stamp(now)>=stamp(p['start_at']):
            raise ValueError('Late registration refused; a new prospective plan is required')
        self.cache.checkpoint([],[(CALLS,[row_for_plan(p,now)])])

    def register_many(self,plans,now):
        existing={x['id']:x for x in self.plans()};rows=[];ids=set()
        for p in plans:
            validate_plan(p)
            if p['id'] in ids:raise ValueError('Duplicate proposed call ID')
            ids.add(p['id'])
            if p['id'] in existing:
                if digest(p)!=digest(existing[p['id']]):raise ValueError('Call ID cannot be rewritten')
                continue
            if p.get('status','Active')=='Active' and stamp(now)>=stamp(p['start_at']):
                raise ValueError('Late registration refused')
            rows.append(row_for_plan(p,now))
        if rows:self.cache.checkpoint([],[(CALLS,rows)])

    def save_result(self,p,result):
        row=[p['id'],p['symbol'],p['type']]+[result[k] if result[k] is not None else '' for k in
          ('status','breakout','retest_observed','confirmation','entry_at','entry_price','exit_at',
           'exit_price','exit_reason','gross_per_share','gross_pnl','net_pnl',
           'observed_mfe_through_exit_minute','observed_mae_through_exit_minute')]+[
           ', '.join(result['missed_targets']),', '.join(result['post_exit_touches']),
           result['missing_minutes'],result['as_of'],result['method'],result['evidence_hash'],
           result['gross_return_pct'] or '',result['estimated_costs'] or '',result['net_return_pct'] or '',
           p.get('quantity') or '',result['last_price'] or '',result['last_at'] or '',
           result['planned_t1_r'],result['planned_t2_r'],result['realized_r'] or '']
        for i in (8,10,12,13,14,15,16,23,24,25,26,27,29,30,31):
            if row[i]!='':row[i]=float(row[i])
        incoming=[[e[k] for k in ('id','call_id','kind','at','price','detail')] for e in result['events']]
        prior={r[0]:r for r in self.cache.snapshot(EVENTS)[1:] if r}
        for e in incoming:
            if e[0] in prior and [str(x) for x in prior[e[0]]]!=[str(x) for x in e]:
                raise ValueError('Previously journaled event changed; provider revision requires review')
        self.cache.checkpoint([(STATUS,row)],[(EVENTS,incoming)])

    def generation_done(self,day):
        return any(len(r)>3 and str(r[1]).startswith(day) and r[2]=='Generation' and
                   r[3] in ('Generated','No Qualified Calls','Capacity Full')
                   for r in self.cache.snapshot(RUNS)[1:])

    def results(self):
        out={}
        for r in self.cache.snapshot(STATUS)[1:]:
            if not r:continue
            def value(i):return r[i] if len(r)>i and r[i]!='' else None
            out[r[0]]={'call_id':r[0],'status':value(3),'entry_at':value(7),'entry_price':value(8),
                       'exit_at':value(9),'gross_pnl':value(13),'net_pnl':value(14),'last_price':value(27),'as_of':value(20)}
        return out

    def portfolio(self,s):
        s=dict(s)
        if 'realized_gross' in s:
            s['realized_estimated_net']=s['realized_gross'];s['realized_roi_pct']=s['gross_roi_pct']
        row=['Short Term Paper Account']+[
            s[k] if s[k] is not None else '' for k in ('initial_capital','realized_estimated_net','realized_roi_pct',
            'unrealized_gross','deployed','reserved','available_cash','selected_calls','review_calls','as_of','cost_note')]
        for i in range(1,9):
            if row[i]!='':row[i]=float(row[i])
        self.cache.checkpoint([(PORTFOLIO,row)],[])

    def run(self,run_id,at,stage,status,count,detail,url,version):
        row=[run_id+'-'+stage,at,stage,status,count,detail,url,version]
        self.cache.checkpoint([(RUNS,row)],[])
