# -*- coding: utf-8 -*-
"""播放量方差分解：账号间 vs 账号内。回答「优化账号状态」还是「优化单条内容」更重要。"""
import re, math
import openpyxl
from collections import defaultdict

wb=openpyxl.load_workbook('J:/project/Perpetua/competitor_viral_20261014.xlsx',read_only=True,data_only=True)
def num(v):
    if v is None: return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).strip().replace(',','')
    m=re.match(r'^([\d.]+)\s*万$',s)
    if m: return float(m.group(1))*10000
    try: return float(s)
    except: return None

rows=[]
for sh in ['bilibili','tiktok','kuaishou']:
    ws=wb[sh]; it=ws.iter_rows(values_only=True); hdr=list(next(it)); ix={h:i for i,h in enumerate(hdr)}
    for r in it:
        if not r or not r[ix['platform']]: continue
        v=num(r[ix['views']]); 
        if not v or v<=0: continue
        rows.append((r[ix['platform']], r[ix['account_name']], math.log10(v), num(r[ix['duration_sec']])))

def icc(data):
    g=defaultdict(list)
    for plat,acct,lv,d in data: g[(plat,acct)].append(lv)
    g={k:v for k,v in g.items() if len(v)>=2}
    N=sum(len(v) for v in g.values()); k=len(g)
    if k<3: return None
    grand=sum(sum(v) for v in g.values())/N
    ssb=sum(len(v)*(sum(v)/len(v)-grand)**2 for v in g.values())
    ssw=sum(sum((x-sum(v)/len(v))**2 for x in v) for v in g.values())
    msb=ssb/(k-1); msw=ssw/(N-k)
    n0=(N-sum(len(v)**2 for v in g.values())/N)/(k-1)
    var_b=max(0,(msb-msw)/n0)
    return dict(k=k,N=N,icc=var_b/(var_b+msw) if (var_b+msw)>0 else 0,
                sd_between=math.sqrt(var_b), sd_within=math.sqrt(msw))

for plat in ['ALL','bilibili','tiktok','kuaishou']:
    d=[r for r in rows if plat=='ALL' or r[0]==plat]
    r=icc(d)
    if r: print(f"{plat:<9} 账号数={r['k']:>3} n={r['N']:>3} ICC={r['icc']:.3f}  log10 组间SD={r['sd_between']:.2f} 组内SD={r['sd_within']:.2f}")

print("\n--- 播放量分布（log10）---")
for plat in ['bilibili','tiktok','kuaishou']:
    d=sorted(r[2] for r in rows if r[0]==plat)
    if not d: continue
    q=lambda p: d[min(len(d)-1,int(p*(len(d)-1)))]
    print(f"{plat:<9} n={len(d):>3} P10={10**q(.1):>12,.0f} P50={10**q(.5):>12,.0f} P90={10**q(.9):>12,.0f} P99={10**q(.99):>12,.0f} max={10**d[-1]:>12,.0f}")

print("\n--- 账号内 时长-播放 相关（仅含>=4条且时长有变异的账号）---")
from statistics import mean
def spearman(xs,ys):
    def rank(a):
        s=sorted(range(len(a)),key=lambda i:a[i]); r=[0]*len(a)
        i=0
        while i<len(s):
            j=i
            while j+1<len(s) and a[s[j+1]]==a[s[i]]: j+=1
            avg=(i+j)/2+1
            for t in range(i,j+1): r[s[t]]=avg
            i=j+1
        return r
    rx,ry=rank(xs),rank(ys); n=len(xs)
    mx,my=mean(rx),mean(ry)
    num_=sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den=(sum((x-mx)**2 for x in rx)*sum((y-my)**2 for y in ry))**0.5
    return num_/den if den else 0

g=defaultdict(list)
for plat,acct,lv,dur in rows:
    if dur and dur>0: g[(plat,acct)].append((dur,lv))
rs=[]
for k,v in g.items():
    if len(v)>=4 and len(set(x[0] for x in v))>=3:
        rho=spearman([x[0] for x in v],[x[1] for x in v]); rs.append((k,rho,len(v)))
if rs:
    pos=sum(1 for _,r,_ in rs if r>0)
    print(f"可用账号={len(rs)}  平均rho={sum(r for _,r,_ in rs)/len(rs):+.3f}  正相关占比={pos}/{len(rs)}")
    for k,r,n in sorted(rs,key=lambda t:-t[1])[:8]: print(f"  {k[0]:<9}{k[1][:18]:<20} rho={r:+.2f} n={n}")
