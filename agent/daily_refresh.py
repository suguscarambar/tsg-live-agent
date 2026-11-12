"""TSG daily early-morning refresh agent (target: 05:30 Europe/Zurich, every day).

1. CASES   scout last-36h news for NEW real-world AI / IoT / Blockchain / RWA / Agentic deployments
           -> LLM extracts the TSG case schema (strict: only facts in the headline/snippet) -> dedupe -> append
2. NEWS    refresh the banner snapshot (top headlines of the day)
3. PUBLISH write tsg-live-data.json  (cases + journals + news, as_of)  -> to be uploaded to the data host
4. SOCIAL  run the Agentic Marketeer (3 posts + pictures) -> approval queue

Usage: python3 daily_refresh.py [--max-new 6] [--no-social]
"""
import argparse, datetime as dt, html, json, os, re, subprocess, sys, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
DB = os.environ.get('TSG_CASES_DB') or os.path.join(ROOT, 'v2', 'tsg_use_cases.json'); OUT = os.environ.get('TSG_OUT') or os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (TSG daily refresh agent)'}
QUERIES = {  # deployment-type news only (launch / pilot / production / partnership)
    'RWA': ['tokenized fund launch', 'tokenized bond issued blockchain', 'tokenization pilot bank'],
    'Blockchain': ['blockchain settlement live bank', 'stablecoin payments launch bank'],
    'AI': ['AI agents deployed production enterprise', 'university AI research breakthrough deployed'],
    'Agentic': ['agentic AI rollout company'],
    'IoT': ['industrial IoT AI deployment', 'IoT blockchain supply chain pilot', 'predictive maintenance AI rollout'],
}
NOISE = r'price|stock (rises|falls|jumps)|shares (rise|fall)|ETF|whale|memecoin|airdrop|prediction|market to reach|CAGR|market size|webinar|podcast|opinion|\?$'
CANON = ['Finance', 'Manufacturing', 'Logistics & Supply Chain', 'Healthcare', 'Energy & Utilities', 'Agriculture & Food',
         'Real Estate', 'Luxury & Retail', 'Public Sector & Research', 'Cross-industry', 'Consumer Goods', 'Mobility']

def get(u, t=15):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r: return r.read().decode('utf-8', 'replace')

def scout():
    out = []
    for topic, qs in QUERIES.items():
        for q in qs:
            items = []
            try: items = re.findall(r'<item>(.*?)</item>', get('https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' when:2d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})), re.S)[:12]
            except Exception as e: print('google fail', q, e)
            try: items += re.findall(r'<item>(.*?)</item>', get('https://www.bing.com/news/search?' + urllib.parse.urlencode({'q': q, 'format': 'rss', 'count': 30, 'qft': 'interval="7"'})), re.S)[:12]
            except Exception as e: print('bing fail', q, e)
            for it in items:
                t = html.unescape(re.search(r'<title>(.*?)</title>', it, re.S).group(1)); src = re.search(r'<source[^>]*>(.*?)</source>', it)
                src = html.unescape(src.group(1)) if src else ''
                if not src: src = (re.search(r'<News:Source>(.*?)</News:Source>', it) or re.search(r'url=https?%3a%2f%2f(?:www\.)?([^%&]+)', it) or [None, 'Bing News'])[1]
                title = t.rsplit(' - ', 1)[0] if ' - ' in t else t
                if re.search(NOISE, title, re.I): continue
                d = re.search(r'<pubDate>(.*?)</pubDate>', it)
                out.append(dict(topic=topic, title=title.strip(), source=src, url=html.unescape((re.search(r'url=(https?%3a[^&<]+)', it) and urllib.parse.unquote(re.search(r'url=(https?%3a[^&<]+)', it).group(1))) or re.search(r'<link>(.*?)</link>', it).group(1)), pub=d.group(1) if d else ''))
    return out

def words(t): return set(w for w in re.findall(r'[a-z0-9]+', t.lower()) if len(w) > 3)
def dup(a, existing): A = words(a); return any(len(A & words(b)) >= 4 for b in existing)

PROMPT = """You maintain a curated database of REAL deployments at the convergence of AI, IoT, Blockchain, RWA tokenization and Agentic AI.
Candidate headlines (index | topic | source | headline):
{lst}
Select at most {n} headlines that describe a concrete, named organisation launching / piloting / deploying / issuing something (not market reports, opinions, prices, funding of generic startups, or events).
For each, return ONLY facts stated or directly implied by the headline. Return strict JSON list:
[{{"i": <index>, "title": "<Org – what was launched/deployed, max 110 chars, en dash>", "org": "<organisation(s)>",
"tech": [subset of "AI","IoT","Blockchain","RWA","Agentic"], "sector": "<one of {canon}>",
"status": "Production"|"Pilot"|"Announced", "city": "<HQ city of the main org, if well known, else ''>", "country": "<ISO-2 or ''>",
"lat": <number or null>, "lon": <number or null>, "kpi": "<one-line value statement from the headline, no invented numbers>"}}]"""

def extract(cands, n):
    from abacusai import ApiClient
    lst = '\n'.join(f"{i} | {c['topic']} | {c['source']} | {c['title']}" for i, c in enumerate(cands))
    r = ApiClient().evaluate_prompt(prompt=PROMPT.format(lst=lst, n=n, canon=', '.join(CANON)), system_message='Return only JSON.')
    return json.loads(re.search(r'\[.*\]', r.content, re.S).group(0))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--max-new', type=int, default=6); ap.add_argument('--no-social', action='store_true'); ap.add_argument('--rules', action='store_true'); a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc); today = now.date().isoformat()
    db = json.load(open(DB)); titles = [c['title'] for c in db['cases']]
    raw = scout(); cands, seen = [], []
    for c in raw:
        if dup(c['title'], titles + seen): continue
        seen.append(c['title']); cands.append(c)
    print(f'scouted {len(raw)}  new candidates {len(cands)}')
    added = []
    ext = []
    if cands and not a.rules:
        try: ext = extract(cands[:60], a.max_new)
        except Exception as ex: print('LLM extract unavailable -> rule-based', str(ex)[:80]); a.rules = True
    if cands and a.rules:
        import rule_extract
        for i, c in enumerate(cands):
            r = rule_extract.extract(c)
            if r and not dup(r['title'], titles + [x['title'] for x in ext]): r['i'] = i; ext.append(r)
            if len(ext) >= a.max_new: break
    for e in ext:
        try:
            c = cands[int(e['i'])]
            if e.get('lat') is None or e.get('lon') is None or not e.get('country'): continue   # map needs a location
            nid = max(x['id'] for x in db['cases']) + 1
            rec = dict(id=nid, title=e['title'], org=e['org'].replace(', ', ' / '), inst=None, tech=[t for t in e['tech'] if t in ('AI', 'IoT', 'Blockchain', 'RWA', 'Agentic')] or [c['topic']],
                       sector=e['sector'], status=e['status'], city=e['city'], country=e['country'], lat=float(e['lat']), lon=float(e['lon']),
                       date=today[:7], year=int(today[:4]), amount=None, kpi=e['kpi'] + f" – via {c['source']}", source=c['url'], pdf=None, added_by='daily-agent', added_on=today)
            db['cases'].append(rec); added.append(rec)
        except Exception as ex: print('skip', ex)
    db['as_of'] = today
    json.dump(db, open(DB, 'w'), ensure_ascii=False, indent=1)
    news = [dict(t=c['title'], s=c['source'], u=c['url'], topic=c['topic']) for c in raw[:12]]
    live = dict(as_of=today, generated_utc=now.strftime('%Y-%m-%d %H:%M UTC'), cases=db['cases'], journals=db['journals'], news=news)
    json.dump(live, open(os.path.join(OUT, 'tsg-live-data.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    log = [f'# TSG daily refresh – {today} ({live["generated_utc"]})', f'- Headlines scouted: {len(raw)}; new candidates: {len(cands)}',
           f'- **New cases added: {len(added)}** → library now {len(db["cases"])} cases', '', '| ID | Tech | Sector | Status | Case | Location |', '|---|---|---|---|---|---|']
    log += [f"| {r['id']} | {'/'.join(r['tech'])} | {r['sector']} | {r['status']} | [{r['title'].replace('|', '/')}]({r['source']}) | {r['city']}, {r['country']} |" for r in added]
    log += ['', 'Locations = HQ of the main organisation (agent-estimated coordinates). Records are added from headlines and carry a NEW badge on tsgag.com on the day they are added.']
    open(os.path.join(OUT, f'refresh_{today}.md'), 'w').write('\n'.join(log))
    print(f'added {len(added)} -> {len(db["cases"])} cases; wrote out/tsg-live-data.json')
    if not a.no_social:
        subprocess.run([sys.executable, os.path.join(ROOT, 'marketeer', 'agentic_marketeer.py'), '--picks', '3', '--date', today], cwd=os.path.join(ROOT, 'marketeer'))

if __name__ == '__main__': main()
