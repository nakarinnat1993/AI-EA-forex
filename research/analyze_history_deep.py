import zipfile, statistics as st, datetime as dt, collections
from xml.etree import ElementTree as ET
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
z=zipfile.ZipFile('/Users/nakarinjaiseengam/Works/AI-EA-forex/data/raw/ReportHistory-28642802.xlsx')
shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS+'si')]
def val(c):
    v=c.find(NS+'v'); t=c.get('t')
    if v is None:
        i=c.find(NS+'is'); return ''.join(x.text or '' for x in i.iter(NS+'t')) if i is not None else ''
    return shared[int(v.text)] if t=='s' else (v.text or '')
rows=ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find(NS+'sheetData').findall(NS+'row')
D={}
for row in rows:
    D[int(row.get('r'))]={''.join(ch for ch in c.get('r') if ch.isalpha()):val(c) for c in row.findall(NS+'c')}
pos=[]
for i in range(8,3468):
    c=D.get(i,{})
    if c.get('D','').strip() not in ('buy','sell'): continue
    try:
        t0=dt.datetime.strptime(c['A'].strip(),'%Y.%m.%d %H:%M:%S'); t1=dt.datetime.strptime(c['I'].strip(),'%Y.%m.%d %H:%M:%S')
    except: continue
    f=lambda k: float(c.get(k,'0').strip() or 0)
    pos.append(dict(t0=t0,t1=t1,side=c['D'].strip(),vol=f('E'),entry=f('F'),
        sl=c.get('G','').strip(),tp=c.get('H','').strip(),exit=f('J'),profit=f('M')))
pos.sort(key=lambda p:p['t0'])
tot_oz=sum(p['vol']*100 for p in pos)
print("total oz traded: %.1f | positions %d" % (tot_oz,len(pos)))
for s in (0.15,0.25,0.35,0.50):
    print("  if spread $%.2f -> spread cost $%.0f (%.0f%% of the $2030 loss)" % (s, s*tot_oz, 100*s*tot_oz/2029.63))
print("\nSL/TP distance (USD): ")
sld=[abs(p['entry']-float(p['sl'])) for p in pos if p['sl']]
tpd=[abs(p['entry']-float(p['tp'])) for p in pos if p['tp']]
print("  SL median %.2f p25 %.2f p75 %.2f | TP median %.2f p25 %.2f p75 %.2f" % (
  st.median(sld),sorted(sld)[len(sld)//4],sorted(sld)[3*len(sld)//4],
  st.median(tpd),sorted(tpd)[len(tpd)//4],sorted(tpd)[3*len(tpd)//4]))
def grp(key,label):
    g=collections.defaultdict(list)
    for p in pos: g[key(p)].append(p['profit'])
    print("\n%s:"%label)
    for k in sorted(g):
        v=g[k]; wr=100*sum(1 for x in v if x>0)/len(v)
        print("  %-12s n=%-5d net=%8.2f  wr=%.0f%%  avg=%.3f" % (k,len(v),sum(v),wr,sum(v)/len(v)))
grp(lambda p:'%02d'%p['t0'].hour,"BY HOUR (broker server time)")
grp(lambda p:['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][p['t0'].weekday()],"BY WEEKDAY")
grp(lambda p:p['t0'].strftime('%Y-%m'),"BY MONTH")
grp(lambda p:'has TP' if p['tp'] else 'NO TP',"TP PRESENT?")
grp(lambda p:'has SL' if p['sl'] else 'NO SL',"SL PRESENT?")
grp(lambda p:p['side'],"SIDE")
# post-loss behaviour
after_l=[pos[i+1]['profit'] for i in range(len(pos)-1) if pos[i]['profit']<0]
after_w=[pos[i+1]['profit'] for i in range(len(pos)-1) if pos[i]['profit']>0]
print("\nAFTER A LOSS: n=%d avg=%.3f wr=%.0f%%" % (len(after_l),st.mean(after_l),100*sum(1 for x in after_l if x>0)/len(after_l)))
print("AFTER A WIN : n=%d avg=%.3f wr=%.0f%%" % (len(after_w),st.mean(after_w),100*sum(1 for x in after_w if x>0)/len(after_w)))
# trades-per-day effect
byday=collections.defaultdict(list)
for p in pos: byday[p['t0'].date()].append(p['profit'])
buckets=collections.defaultdict(list)
for d,v in byday.items():
    b = '1-5' if len(v)<=5 else '6-15' if len(v)<=15 else '16-30' if len(v)<=30 else '31+'
    buckets[b].append(sum(v))
print("\nDAILY NET by trade-count bucket:")
for b in ['1-5','6-15','16-30','31+']:
    if b in buckets: print("  %-6s days=%-4d avg daily net=%7.2f  total=%8.2f" % (b,len(buckets[b]),st.mean(buckets[b]),sum(buckets[b])))
# exit reason
def reason(p):
    if p['tp'] and abs(p['exit']-float(p['tp']))<0.05: return 'TP hit'
    if p['sl'] and abs(p['exit']-float(p['sl']))<0.05: return 'SL hit'
    return 'manual/other'
grp(reason,"EXIT REASON")
