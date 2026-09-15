import zipfile, datetime as dt, collections
from xml.etree import ElementTree as ET
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
z=zipfile.ZipFile('/Users/nakarinjaiseengam/Works/AI-EA-forex/data/raw/ReportHistory-28642802.xlsx')
shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS+'si')]
def val(c):
    v=c.find(NS+'v'); t=c.get('t')
    if v is None:
        i=c.find(NS+'is'); return ''.join(x.text or '' for x in i.iter(NS+'t')) if i is not None else ''
    return shared[int(v.text)] if t=='s' else (v.text or '')
D={}
for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find(NS+'sheetData').findall(NS+'row'):
    D[int(row.get('r'))]={''.join(ch for ch in c.get('r') if ch.isalpha()):val(c) for c in row.findall(NS+'c')}
pos=[]
for i in range(8,3468):
    c=D.get(i,{})
    if c.get('D','').strip() not in ('buy','sell'): continue
    try:
        t0=dt.datetime.strptime(c['A'].strip(),'%Y.%m.%d %H:%M:%S'); t1=dt.datetime.strptime(c['I'].strip(),'%Y.%m.%d %H:%M:%S')
    except: continue
    f=lambda k: float(c.get(k,'0').strip() or 0)
    pos.append(dict(t0=t0,t1=t1,side=c['D'].strip(),entry=f('F'),sl=c.get('G','').strip(),exit=f('J'),profit=f('M')))

# ตรวจ "SL blowthrough" = ปิดเลย SL ไปมาก -> ราคาวิ่งเร็วผิดปกติ (news spike)
ev=[]
for p in pos:
    if not p['sl']: continue
    sl=float(p['sl'])
    if p['side']=='sell': over = p['exit']-sl      # sell: SL อยู่เหนือ entry
    else:                 over = sl-p['exit']
    if over > 1.0:  # ทะลุ SL เกิน $1
        ev.append((p['t1'], over, p['profit']))
ev.sort()
print("จำนวนเหตุการณ์ SL blowthrough > $1 :", len(ev))

print("\n=== การกระจายตามนาทีของวัน (server) — เฉพาะ blowthrough > $3 ===")
big=[e for e in ev if e[1]>3.0]
cnt=collections.Counter((e[0].hour, e[0].minute//30*30) for e in big)
for (h,m),n in sorted(cnt.items(), key=lambda x:-x[1])[:12]:
    print("  server %02d:%02d-%02d:%02d  n=%d" % (h,m,h,m+29,n))

print("\n=== แยกฤดู: เหตุการณ์ใหญ่ (>$3) ในช่วง 14:00-17:00 server ===")
# US DST 2026: 8 มี.ค. - 1 พ.ย. ; 2025: 9 มี.ค. - 2 พ.ย.
def is_us_dst(d):
    if d.year==2025: return dt.date(2025,3,9) <= d.date() <= dt.date(2025,11,2)
    if d.year==2026: return dt.date(2026,3,8) <= d.date() <= dt.date(2026,11,1)
    return False
for label,f in (("US DST (ฤดูร้อน)", lambda d: is_us_dst(d)), ("ไม่ DST (ฤดูหนาว)", lambda d: not is_us_dst(d))):
    sub=[e for e in big if f(e[0]) and 14<=e[0].hour<=17]
    c=collections.Counter((e[0].hour, e[0].minute//15*15) for e in sub)
    print("  %s : n=%d" % (label,len(sub)))
    for (h,m),n in sorted(c.items()):
        if n>=1: print("      %02d:%02d-%02d:%02d  n=%d" % (h,m,h,m+14,n))

print("\n=== 15 เหตุการณ์ที่ทะลุ SL หนักสุด ===")
for t,over,pl in sorted(ev,key=lambda x:-x[1])[:15]:
    print("  %s (%s)  ทะลุ SL $%.2f  P&L %.2f  [DST=%s]" % (
        t.strftime('%Y-%m-%d %H:%M:%S'), ['จ','อ','พ','พฤ','ศ','ส','อา'][t.weekday()], over, pl, 'Y' if is_us_dst(t) else 'N'))

print("\n=== เค้นฤดูหนาว: ไม้ที่ขาดทุนหนัก (<-6) ในเดือน พ.ย.2025-ก.พ.2026 ===")
win=[p for p in pos if not is_us_dst(p['t0']) and p['profit']<-6]
c=collections.Counter((p['t0'].hour, p['t0'].minute//30*30) for p in win)
print("  รวม %d ไม้ | ช่วงเวลาที่กระจุก:" % len(win))
for (h,m),n in sorted(c.items(), key=lambda x:-x[1])[:10]:
    print("      server %02d:%02d-%02d:%02d  n=%d" % (h,m,h,m+29,n))
print("\n  ไม้ที่เปิด/ปิดคาบเกี่ยว 15:25-15:35 หรือ 16:25-16:35 ในฤดูหนาว:")
for p in pos:
    if is_us_dst(p['t0']): continue
    for t,lbl in ((p['t0'],'เปิด'),(p['t1'],'ปิด')):
        if (t.hour==15 or t.hour==16) and 25<=t.minute<=35:
            print("      %s %s  P&L %6.2f  %s" % (t.strftime('%Y-%m-%d %H:%M:%S'), lbl, p['profit'], ['จ','อ','พ','พฤ','ศ','ส','อา'][t.weekday()]))
