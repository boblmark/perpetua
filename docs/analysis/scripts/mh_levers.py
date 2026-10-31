# -*- coding: utf-8 -*-
"""账号分层 Mantel-Haenszel 复算：竞品抽样是「每账号 5 爆款 + 5 对照」的匹配设计，
朴素 Fisher 会混入账号层混杂（粉丝量/风格/时期）。这里按账号分层，估计条件 OR。"""
import re, math, json, sys
import openpyxl
from collections import defaultdict

WB = 'J:/project/Perpetua/competitor_viral_20261014.xlsx'
wb = openpyxl.load_workbook(WB, read_only=True, data_only=True)

def num(v):
    if v is None: return None
    if isinstance(v,(int,float)): return float(v)
    s=str(v).strip().replace(',','')
    m=re.match(r'^([\d.]+)\s*万$', s)
    if m: return float(m.group(1))*10000
    try: return float(s)
    except: return None

rows=[]
for sh in ['bilibili','tiktok','kuaishou','x']:
    ws=wb[sh]; it=ws.iter_rows(values_only=True)
    hdr=list(next(it))
    idx={h:i for i,h in enumerate(hdr)}
    for r in it:
        if not r or not r[idx['platform']]: continue
        rows.append(dict(
            plat=r[idx['platform']], acct=r[idx['account_name']],
            views=num(r[idx['views']]), dur=num(r[idx['duration_sec']]),
            title=(r[idx['title']] or ''), cover=(r[idx['cover_desc']] or ''),
            hook=r[idx['hook_type']] or '', topic=r[idx['topic_category']] or '',
            viral=int(r[idx['is_viral']] or 0), pub=r[idx['published_at']] or '',
            likes=num(r[idx['likes']]), shares=num(r[idx['shares']]) if 'shares' in idx else None,
        ))

FEATS = {}
def add(name, fn): FEATS[name]=fn
add('dur_lt15',  lambda x: x['dur'] is not None and x['dur']<15)
add('dur_15_60', lambda x: x['dur'] is not None and 15<=x['dur']<60)
add('dur_60_180',lambda x: x['dur'] is not None and 60<=x['dur']<180)
add('dur_ge180', lambda x: x['dur'] is not None and x['dur']>=180)
add('has_number',lambda x: bool(re.search(r'\d', x['title'])))
add('has_question',lambda x: ('?' in x['title']) or ('？' in x['title']))
add('has_emoji', lambda x: bool(re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', x['title'])))
add('has_dash',  lambda x: ('—' in x['title']) or ('…' in x['title']) or ('--' in x['title']))
add('has_series',lambda x: bool(re.search(r'第\s*[0-9一二三四五六七八九十]+\s*[集季]|EP\s*\d+|ep\s*\d+', x['title'])))
add('has_ai',    lambda x: bool(re.search(r'\bAI\b|ai生成|AIGC', x['title'])))
add('cover_text',lambda x: x['cover'] not in ('','N/A','ccden'))
add('hook_state',lambda x: x['hook']=='陈述开场')
add('hook_conf', lambda x: x['hook'] in ('对比冲突','反转预期','悬念提问'))

def mh(strata, feat):
    """strata: {(plat,acct): [rows]} -> MH OR + RBG 95%CI"""
    R=S=0.0; PR=PS=0.0; Q=0.0
    used=0; n_exp=0
    for k,grp in strata.items():
        a=b=c=d=0
        for x in grp:
            e=feat(x); v=x['viral']
            if e and v: a+=1
            elif e and not v: b+=1
            elif (not e) and v: c+=1
            else: d+=1
        n=a+b+c+d
        if n==0: continue
        used+=1; n_exp+=a+b
        if a+b==0 or c+d==0: continue
        R += a*d/n; S += b*c/n
        P=(a+d)/n; Q=(b+c)/n
        PR += P*R if False else 0
        PR += (a+d)/n * (a*d)/n
        PS += (a+d)/n * (b*c)/n
        Q  += (a+d)*(b+c)/n
    if S==0 or R==0: return None
    orv=R/S
    # RBG variance of ln(OR_MH)
    var = PR/(2*R*R) + PS/(2*S*S) + Q/(2*R*S)
    se=math.sqrt(var)
    lo=math.exp(math.log(orv)-1.96*se); hi=math.exp(math.log(orv)+1.96*se)
    z=math.log(orv)/se if se>0 else 0
    p=2*(1-0.5*(1+math.erf(abs(z)/math.sqrt(2))))
    return dict(or_=orv, lo=lo, hi=hi, p=p, strata=used, n_exp=n_exp)

out=[]
for plat in ['ALL','bilibili','tiktok','kuaishou']:
    sub=[r for r in rows if (plat=='ALL' or r['plat']==plat) and r['views'] is not None or (plat!='ALL' and r['plat']==plat)]
    sub=[r for r in rows if plat=='ALL' or r['plat']==plat]
    strata=defaultdict(list)
    for r in sub: strata[(r['plat'],r['acct'])].append(r)
    for name,fn in FEATS.items():
        res=mh(strata,fn)
        if res: out.append((plat,name,res))

print(f"{'平台':<10}{'特征':<14}{'OR':>7}{'95%CI':>18}{'p':>9}{'层':>5}{'暴露':>6}")
for plat,name,r in out:
    ci=f"[{r['lo']:.2f},{r['hi']:.2f}]"
    print(f"{plat:<10}{name:<14}{r['or_']:>7.2f}{ci:>18}{r['p']:>9.3f}{r['strata']:>5}{r['n_exp']:>6}")

# 时长-播放（平台内，账号内 z 分位）
print("\n--- 各平台时长档 播放中位数（原始，仅描述）---")
for plat in ['bilibili','tiktok','kuaishou']:
    d=defaultdict(list)
    for r in rows:
        if r['plat']!=plat or r['views'] is None or r['dur'] is None: continue
        b = '<15s' if r['dur']<15 else '15-60s' if r['dur']<60 else '60-180s' if r['dur']<180 else '>=180s'
        d[b].append(r['views'])
    print(plat, {k:(len(v), int(sorted(v)[len(v)//2])) for k,v in sorted(d.items())})
