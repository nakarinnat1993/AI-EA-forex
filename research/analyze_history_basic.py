import zipfile, statistics as st, datetime as dt
from xml.etree import ElementTree as ET
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
p='/Users/nakarinjaiseengam/Works/AI-EA-forex/data/raw/ReportHistory-28642802.xlsx'
z=zipfile.ZipFile(p)
shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS+'si')]
def val(c):
    v=c.find(NS+'v'); t=c.get('t')
    if v is None:
        isel=c.find(NS+'is'); return ''.join(x.text or '' for x in isel.iter(NS+'t')) if isel is not None else ''
    return shared[int(v.text)] if t=='s' else (v.text or '')
rows=ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find(NS+'sheetData').findall(NS+'row')
data={}
for row in rows:
    cells={}
    for c in row.findall(NS+'c'):
        ref=c.get('r'); col=''.join(ch for ch in ref if ch.isalpha())
        cells[col]=val(c)
    data[int(row.get('r'))]=cells
def col(cells,c): return cells.get(c,'').strip()
pos=[]
for i in range(8,3468):
    c=data.get(i,{})
    if not col(c,'A') or col(c,'D') not in ('buy','sell'): continue
    try:
        t0=dt.datetime.strptime(col(c,'A'),'%Y.%m.%d %H:%M:%S')
        t1=dt.datetime.strptime(col(c,'I'),'%Y.%m.%d %H:%M:%S')
    except: continue
    pos.append(dict(t0=t0,t1=t1,sym=col(c,'C'),side=col(c,'D'),vol=float(col(c,'E') or 0),
        entry=float(col(c,'F') or 0), sl=col(c,'G'), tp=col(c,'H'), exit=float(col(c,'J') or 0),
        comm=float(col(c,'K') or 0), swap=float(col(c,'L') or 0), profit=float(col(c,'M') or 0)))
print("TOTAL POSITIONS:", len(pos))
print("DATE RANGE:", min(p['t0'] for p in pos), "->", max(p['t1'] for p in pos))
days=len(set(p['t0'].date() for p in pos)); print("TRADING DAYS:", days, " avg trades/day:", round(len(pos)/days,1))
print("SYMBOLS:", {s:sum(1 for p in pos if p['sym']==s) for s in set(p['sym'] for p in pos)})
print("VOLUMES:", sorted(set(p['vol'] for p in pos))[:12])
net=sum(p['profit']+p['comm']+p['swap'] for p in pos)
print("NET P&L: %.2f | gross profit %.2f | commission %.2f | swap %.2f" % (net, sum(p['profit'] for p in pos), sum(p['comm'] for p in pos), sum(p['swap'] for p in pos)))
w=[p for p in pos if p['profit']>0]; l=[p for p in pos if p['profit']<0]; b=[p for p in pos if p['profit']==0]
print("WIN %d (%.1f%%) LOSS %d BE %d" % (len(w),100*len(w)/len(pos),len(l),len(b)))
print("avg win %.2f | avg loss %.2f | RR %.2f" % (st.mean(x['profit'] for x in w), st.mean(x['profit'] for x in l), abs(st.mean(x['profit'] for x in w)/st.mean(x['profit'] for x in l))))
print("expectancy/trade: %.3f USD" % (net/len(pos)))
hold=[(p['t1']-p['t0']).total_seconds()/60 for p in pos]
print("HOLD MIN: median %.1f | mean %.1f | p90 %.1f | max %.1f" % (st.median(hold), st.mean(hold), sorted(hold)[int(.9*len(hold))], max(hold)))
hw=[(p['t1']-p['t0']).total_seconds()/60 for p in w]; hl=[(p['t1']-p['t0']).total_seconds()/60 for p in l]
print("  hold median WIN %.1f min | LOSS %.1f min" % (st.median(hw), st.median(hl)))
nosl=sum(1 for p in pos if not p['sl']); notp=sum(1 for p in pos if not p['tp'])
print("NO SL: %d (%.1f%%) | NO TP: %d (%.1f%%)" % (nosl,100*nosl/len(pos),notp,100*notp/len(pos)))
print("worst 5:", [round(p['profit'],2) for p in sorted(pos,key=lambda x:x['profit'])[:5]])
print("best 5:", [round(p['profit'],2) for p in sorted(pos,key=lambda x:-x['profit'])[:5]])
print("--- RESULTS SECTION ---")
for i in range(18123,18136):
    c=data.get(i,{})
    s=' | '.join(v for v in c.values() if v.strip())
    if s: print(i,':',s)
