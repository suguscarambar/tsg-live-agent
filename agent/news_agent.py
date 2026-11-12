"""TSG Live News agent - finds ALL relevant news for the 6 TSG topics and keeps a growing archive since 2025-01-01.

Topics: IoT · Blockchain · RWA Tokenization · AI · Agentic AI · University Journals
Sources (one polite lane per host, auto-skips a host that rate-limits):
  0. GDELT DOC API - one wide OR-query per topic (250 articles/call; used for the backfill since 2025)
  0b. Bing News RSS - same queries as Google (fallback when Google throttles)
  1. Google News RSS - 6-9 targeted queries per topic (daily: when:2d; backfill: quarterly windows since 2025-01-01)
  2. Direct RSS feeds - university newsrooms (MIT, Harvard, Cambridge, Berkeley), journals (Nature ML, ScienceDaily AI),
     trade press (Ledger Insights, The Block, Cointelegraph tokenization, IoT Business News, TechCrunch AI, MIT Tech Review, Unite.AI)
Pipeline: fetch (parallel) -> clean -> noise filter -> topic classifier (keyword rules, multi-label) -> relevance score
          -> dedupe (URL + title similarity, keeps the earliest/best source) -> merge into news_archive.json -> stats
Usage:  python3 news_agent.py            # daily run (last 2 days + feeds)
        python3 news_agent.py --backfill # one-off: fill archive back to 2025-01-01
"""
import argparse, concurrent.futures as cf, datetime as dt, email.utils, html, json, os, re, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ARCH = os.environ.get('TSG_NEWS_ARCHIVE') or os.path.join(HERE, 'out', 'news_archive.json')
os.makedirs(os.path.dirname(ARCH), exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36'}
START = dt.date(2025, 1, 1)
TOPICS = ['IoT', 'Blockchain', 'RWA', 'AI', 'Agentic', 'University']
LABEL = {'IoT': 'IoT', 'Blockchain': 'Blockchain', 'RWA': 'RWA Tokenization', 'AI': 'AI', 'Agentic': 'Agentic AI', 'University': 'University Journals'}
UNI = r'MIT|Massachusetts Institute|Stanford|Harvard|ETH Z|EPFL|Oxford|Cambridge|Berkeley|Yale|Imperial College|Princeton|Carnegie Mellon|Caltech|Columbia University|University|Universit[äa]t|Institute of Technology|researchers|study finds|scientists'
QUERIES = {
    'IoT': ['industrial IoT deployment', '"internet of things" AI', 'IoT sensors predictive maintenance', 'IIoT digital twin factory',
            'IoT blockchain supply chain', 'smart grid IoT launch', 'edge AI IoT devices', 'IoT platform partnership'],
    'Blockchain': ['blockchain bank settlement', 'stablecoin launch bank', 'enterprise blockchain partnership', 'distributed ledger central bank',
                   'blockchain payments live', 'CBDC pilot', 'blockchain supply chain traceability', 'tokenized deposits'],
    'RWA': ['tokenized fund', 'real world assets tokenization', 'RWA tokenization', 'tokenized treasury', 'tokenized bond issuance',
            'tokenized real estate', 'tokenized money market fund', 'tokenization asset manager', 'digital securities tokenized'],
    'AI': ['enterprise AI deployment', 'generative AI rollout bank', 'AI manufacturing deployment', 'AI healthcare deployment hospital',
           'AI regulation EU AI Act', 'foundation model launch enterprise', 'AI partnership production'],
    'Agentic': ['agentic AI', '"AI agents" enterprise', 'agentic AI deployment', 'autonomous AI agents company', 'AI agent platform launch',
                'multi-agent system', 'agentic commerce payments'],
    'University': ['university researchers artificial intelligence', 'university blockchain research', 'university IoT research',
                   'MIT researchers AI', 'Stanford researchers AI', 'ETH Zurich AI research', 'Oxford Cambridge AI study',
                   'university tokenization research', 'journal study machine learning breakthrough'],
}
FEEDS = [  # (url, default topic, source label)
    ('https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml', 'University', 'MIT News'),
    ('https://news.mit.edu/rss/topic/blockchain', 'University', 'MIT News'),
    ('https://news.harvard.edu/gazette/feed/', 'University', 'Harvard Gazette'),
    ('https://www.cam.ac.uk/news/feed', 'University', 'University of Cambridge'),
    ('https://news.berkeley.edu/feed/', 'University', 'UC Berkeley News'),
    ('https://www.nature.com/subjects/machine-learning.rss', 'University', 'Nature'),
    ('https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml', 'University', 'ScienceDaily'),
    ('https://www.ledgerinsights.com/feed/', 'RWA', 'Ledger Insights'),
    ('https://cointelegraph.com/rss/tag/tokenization', 'RWA', 'Cointelegraph'),
    ('https://www.theblock.co/rss.xml', 'Blockchain', 'The Block'),
    ('https://iotbusinessnews.com/feed/', 'IoT', 'IoT Business News'),
    ('https://techcrunch.com/category/artificial-intelligence/feed/', 'AI', 'TechCrunch'),
    ('https://www.technologyreview.com/feed/', 'AI', 'MIT Technology Review'),
    ('https://www.unite.ai/feed/', 'AI', 'Unite.AI'),
]
RULES = {  # multi-label topic classifier on title (+ summary)
    'Agentic': r'agentic|ai agents?\b|autonomous agents?|multi-agent|agent(ic)? (ai|platform|workflow|commerce)|copilot agents?|agentforce|a2a|model context protocol|\bmcp\b',
    'RWA': r'tokeni[sz](ation|ed|e|ing)\b|real[- ]world assets?|\brwa\b|on-?chain (fund|treasur|bond|asset)|digital (bond|securit)|money[- ]market fund.{0,30}(chain|token)|buidl|benji|security tokens?',
    'Blockchain': r'blockchain|distributed ledger|\bdlt\b|stablecoin|\bcbdc\b|smart contract|ethereum|solana|avalanche|hyperledger|polygon|on-?chain|crypto(currency)? (bank|custody|payments)|digital euro|tokenized deposit',
    'IoT': r'\biot\b|iiot|internet of things|sensors?\b|digital twin|edge (ai|computing|devices?)|smart (grid|meter|factory|city|building)|connected (devices?|vehicles?)|predictive maintenance|telematics|wearables?',
    'AI': r'\bai\b|artificial intelligence|machine learning|deep learning|\bllms?\b|generative|genai|neural|foundation model|gpt|gemini|claude|chatbot|computer vision',
    'University': r'(' + UNI + r').{0,80}(research|study|lab|develop|scientists|paper|journal)|\bjournal\b|peer-reviewed|nature (study|paper)|arxiv',
}
TECH = r'\bai\b|artificial intelligence|machine learning|deep learning|agentic|ai agents?|blockchain|ledger|tokeni|stablecoin|\biot\b|internet of things|sensors?\b|robot|neural|digital twin|\bllms?\b|chatgpt|generative'
NOISE = (r'price (prediction|analysis)|\bprice\b.{0,20}(surge|drop|jump|rall|crash|soar|slump)|(stock|shares)\s+(rise|fall|jump|soar|slump|surge)|\bETF (flows|inflows|outflows)\b|whales?\b|memecoin|meme coin|airdrop|'
         r'market (to reach|size|share|report|forecast)|CAGR|\bwebinar\b|\bpodcast\b|sponsored|press release distribution|horoscope|top \d+ (coins|crypto)|could (hit|reach) \$|bitcoin (price|falls|rises)|technical analysis|'
         r'^(show|launch|tell|ask) hn|\| opinion|^opinion|explainer videos|in 15 minutes|\d+-minute (it )?news|the download:|giveaway|casino|betting|\bdeals? of the day\b|best (vpn|laptop|phone)')

JUNK_SRC = r'github\.(com|io)|gitlab|youtube\.com|youtu\.be|twitter\.com|x\.com$|reddit\.com|news\.ycombinator|huggingface\.co$'

def get(u, t=20):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r: return r.read().decode('utf-8', 'replace')

def tag(it, name):
    m = re.search(r'<%s[^>]*>(.*?)</%s>' % (name, name), it, re.S)
    if not m: return ''
    v = m.group(1).strip()
    v = re.sub(r'^<!\[CDATA\[(.*)\]\]>$', r'\1', v, flags=re.S)
    return html.unescape(re.sub(r'<[^>]+>', ' ', html.unescape(v))).replace('\xa0', ' ').strip()

def pdate(s):
    try: return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc)
    except Exception:
        try: return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(dt.timezone.utc)
        except Exception: return None

def parse(xml, topic, label, gnews):
    out = []
    for it in re.findall(r'<(?:item|entry)\b.*?</(?:item|entry)>', xml, re.S):
        t = re.sub(r'\s+', ' ', tag(it, 'title'))
        src = tag(it, 'source') if gnews else label
        if gnews and ' - ' in t: t, s2 = t.rsplit(' - ', 1); src = src or s2
        link = tag(it, 'link') or (re.search(r'<link[^>]*href="([^"]+)"', it) or [None, ''])[1]
        d = pdate(tag(it, 'pubDate') or tag(it, 'published') or tag(it, 'updated') or tag(it, 'dc:date'))
        summ = '' if gnews else re.sub(r'\s+', ' ', tag(it, 'description') or tag(it, 'summary'))[:400]
        if t and link and d: out.append(dict(t=t.strip(), s=(src or label).strip(), u=link.strip(), d=d.strftime('%Y-%m-%dT%H:%MZ'), q=topic, x=summ))
    return out

def gnews_url(q, window):
    return 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' ' + window, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})

def bing_url(q):
    return 'https://www.bing.com/news/search?' + urllib.parse.urlencode({'q': q, 'format': 'rss', 'count': 50, 'qft': 'interval="7"'})

GDELT_Q = {  # one wide OR-query per topic (GDELT: 250 articles per call, archive back to 2017)
    'IoT': '("internet of things" OR IIoT OR "industrial IoT" OR "IoT sensors" OR "digital twin" OR "predictive maintenance" OR "IoT platform")',
    'Blockchain': '("distributed ledger" OR "blockchain settlement" OR "blockchain platform" OR "stablecoin launch" OR CBDC OR "tokenized deposits" OR "enterprise blockchain")',
    'RWA': '(tokenization OR tokenized OR tokenised OR "real world assets" OR "real-world assets")',
    'AI': '("generative AI" OR "artificial intelligence") (deploys OR deployment OR rollout OR "rolls out" OR launches OR partnership)',
    'Agentic': '("agentic AI" OR "AI agents" OR "AI agent" OR "multi-agent")',
    'University': '(university OR researchers OR professor) ("artificial intelligence" OR "machine learning" OR blockchain OR "internet of things" OR tokenization)',
}
def gdelt_url(q, d0, d1):
    return 'https://api.gdeltproject.org/api/v2/doc/doc?' + urllib.parse.urlencode({'query': q + ' sourcelang:english', 'mode': 'artlist', 'format': 'json',
        'maxrecords': 250, 'sort': 'HybridRel', 'startdatetime': d0.strftime('%Y%m%d000000'), 'enddatetime': d1.strftime('%Y%m%d000000')})

HN_Q = {'IoT': ['IoT', 'internet of things', 'industrial IoT', 'digital twin'], 'Blockchain': ['blockchain', 'stablecoin', 'CBDC', 'distributed ledger'],
        'RWA': ['tokenization', 'tokenized', 'real world assets'], 'AI': ['enterprise AI', 'generative AI'], 'Agentic': ['AI agents', 'agentic'],
        'University': ['MIT researchers', 'Stanford researchers', 'university researchers AI']}
PAGED = [  # WordPress-style archives that page back past 2025-01-01 (url template, topic, label, max pages)
    ('https://iotbusinessnews.com/feed/?paged={}', 'IoT', 'IoT Business News', 45),
    ('https://news.harvard.edu/gazette/feed/?paged={}', 'University', 'Harvard Gazette', 24),
    ('https://news.berkeley.edu/feed/?paged={}', 'University', 'UC Berkeley News', 60),
    ('https://cointelegraph.com/rss/tag/tokenization?page={}', 'RWA', 'Cointelegraph', 40),
]
def hn_url(q, t0, t1):
    return 'https://hn.algolia.com/api/v1/search_by_date?' + urllib.parse.urlencode({'query': q, 'tags': 'story', 'hitsPerPage': 100,
        'numericFilters': f'created_at_i>{int(t0.timestamp())},created_at_i<{int(t1.timestamp())},points>2'})
def parse_hn(txt, topic):
    out = []
    for h in json.loads(txt).get('hits', []):
        if not h.get('url') or not h.get('title'): continue
        out.append(dict(t=h['title'], s=HOSTNAME(h['url']), u=h['url'], d=dt.datetime.fromtimestamp(h['created_at_i'], dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), q=topic, x=''))
    return out

def parse_gdelt(txt, topic):
    out = []
    for a in (json.loads(txt).get('articles') or []):
        try: d = dt.datetime.strptime(a['seendate'], '%Y%m%dT%H%M%SZ')
        except Exception: continue
        out.append(dict(t=html.unescape(a.get('title', '')).strip(), s=a.get('domain', ''), u=a['url'], d=d.strftime('%Y-%m-%dT%H:%MZ'), q=topic, x=''))
    return out

def classify(r):
    title, text = r['t'], r['t'] + ' ' + r.get('x', '')
    k = [tp for tp in TOPICS if re.search(RULES[tp], title, re.I)]
    if 'RWA' in k and re.search(r'tokenizer|\bbpe\b|language model|\bllm|token(s)? per|vocabular', title, re.I): k.remove('RWA')
    if r['q'] == 'University' and r['s'] in ('MIT News', 'Harvard Gazette', 'University of Cambridge', 'UC Berkeley News', 'Nature', 'ScienceDaily'):
        if not re.search(TECH, title, re.I): return []         # university feed but headline not about tech -> drop
        k = ['University'] + [x for x in k if x != 'University']
    elif not re.search(r'Technology Review', r['s']) and re.search(r'\.edu\b|universit|\bMIT\b|Stanford|Harvard|ETH Z|Oxford|Cambridge|Berkeley|Yale|Imperial College|Nature|Science(Daily)?\b|journal', r['s'], re.I) and 'University' not in k and k:
        k.append('University')
    if 'Agentic' in k and 'AI' in k: k.remove('AI')            # agentic implies AI - keep the sharper label
    if 'RWA' in k and 'Blockchain' in k and not re.search(RULES['Blockchain'], title.replace('on-chain', ''), re.I): k.remove('Blockchain')
    return k

def score(r):
    s = len(r['k']) * 2 + (3 if re.search(r'launch|deploy|pilot|live|partner|issu|roll(s|ed)? out|first|go(es)? live|production|announce|unveil|introduc', r['t'], re.I) else 0)
    s += 2 if r['q'] in r['k'] else 0
    s += 1 if re.search(r'Reuters|Bloomberg|Financial Times|CNBC|Wall Street Journal|Forbes|TechCrunch|MIT|Nature|Ledger Insights|The Block|CoinDesk|Business Wire|PR Newswire', r['s']) else 0
    return s

def HOSTNAME(u):
    try: return urllib.parse.urlparse(u).hostname.replace('www.', '')
    except Exception: return 'News'

def words(t): return frozenset(w for w in re.findall(r'[a-z0-9]+', t.lower()) if len(w) > 3)
def similar(a, b): return len(a & b) >= max(4, int(0.6 * min(len(a), len(b))))

def run(backfill=False):
    now = dt.datetime.now(dt.timezone.utc)
    lanes = {'google': [], 'bing': [], 'gdelt': [], 'feeds': [], 'hn': [], 'paged': []}   # one lane per host, polite spacing inside each lane
    if backfill:
        d = START
        while d < now.date():
            e = min(d + dt.timedelta(days=30), now.date() + dt.timedelta(days=1))
            for tp, q in GDELT_Q.items(): lanes['gdelt'].append((gdelt_url(q, d, e), tp, 'GDELT', 'gdelt'))
            for tp, qs in QUERIES.items():
                for q in qs[:3]: lanes['google'].append((gnews_url(q, f'after:{d.isoformat()} before:{e.isoformat()}'), tp, 'Google News', 'rss-g'))
            d = e
        d = dt.datetime(START.year, START.month, START.day, tzinfo=dt.timezone.utc)
        while d < now:
            e = min(d + dt.timedelta(days=61), now)
            for tp, qs in HN_Q.items():
                for q in qs: lanes['hn'].append((hn_url(q, d, e), tp, 'HN', 'hn'))
            d = e
        for u, tp, lab, mx in PAGED:
            for pg in range(2, mx + 1): lanes['paged'].append((u.format(pg), tp, lab, 'rss'))
    else:
        for tp, qs in QUERIES.items():
            for q in qs:
                lanes['google'].append((gnews_url(q, 'when:2d'), tp, 'Google News', 'rss-g'))
                lanes['bing'].append((bing_url(q), tp, 'Bing News', 'rss-b'))
        for tp, q in GDELT_Q.items(): lanes['gdelt'].append((gdelt_url(q, now - dt.timedelta(days=2), now + dt.timedelta(days=1)), tp, 'GDELT', 'gdelt'))
    lanes['feeds'] = [(u, tp, lab, 'rss') for u, tp, lab in FEEDS]
    GAP = {'google': 2.0, 'bing': 1.2, 'gdelt': 5.5, 'feeds': 0.2, 'hn': 0.4, 'paged': 0.8}
    stat = {k: [0, 0, 0] for k in lanes}   # ok, failed, items
    def lane(name):
        res, blocked = [], 0
        for j in lanes[name]:
            if blocked >= (8 if name == 'gdelt' else 3): stat[name][1] += 1; continue          # host is rate-limiting us -> stop hammering it
            try:
                txt = get(j[0])
                items = parse_gdelt(txt, j[1]) if j[3] == 'gdelt' else parse_hn(txt, j[1]) if j[3] == 'hn' else parse(txt, j[1], j[2], j[3] != 'rss')
                if j[3] == 'rss-b':
                    for r in items:
                        m = re.search(r'[?&]url=([^&]+)', r['u']); r['u'] = urllib.parse.unquote(m.group(1)) if m else r['u']
                        if r['s'] == 'Bing News': r['s'] = HOSTNAME(r['u'])
                res += items; stat[name][0] += 1; stat[name][2] += len(items); blocked = 0
            except Exception as e:
                stat[name][1] += 1; blocked += 1 if re.search(r'429|503|403', str(e)) else 0
                if name == 'gdelt': time.sleep(15)
                if blocked == 3: print(f'{name}: rate-limited ({e}) - skipping the rest of this lane today')
            time.sleep(GAP[name])
        return res
    raw = []
    with cf.ThreadPoolExecutor(len(lanes)) as ex:
        for r in ex.map(lane, list(lanes)): raw += r
    jobs = sum(len(v) for v in lanes.values()); fails = sum(v[1] for v in stat.values())
    print('lanes', {k: f'ok {v[0]} / failed {v[1]} / items {v[2]}' for k, v in stat.items()})
    print(f'requests {jobs} (failed {fails})  raw items {len(raw)}')
    arch = json.load(open(ARCH)) if os.path.exists(ARCH) else {'items': []}
    items = arch['items']; urls = {i['u'] for i in items}; sigs = [(words(i['t']), i) for i in items]
    added = dropped_noise = dropped_off = dup = 0
    for r in sorted(raw, key=lambda r: r['d']):
        if r['d'][:10] < START.isoformat(): continue
        if re.search(NOISE, r['t'], re.I) or len(r['t']) < 25 or re.search(JUNK_SRC, r['s'] or '', re.I): dropped_noise += 1; continue
        k = classify(r)
        if not k: dropped_off += 1; continue
        r['k'] = k; w = words(r['t'])
        if r['u'] in urls: dup += 1; continue
        hit = next((i for s, i in sigs if similar(w, s) and abs((dt.datetime.fromisoformat(i['d'][:10]) - dt.datetime.fromisoformat(r['d'][:10])).days) <= 4), None)
        if hit:  # same story from another outlet -> count it, keep one card
            dup += 1; hit['n'] = hit.get('n', 1) + 1; hit['k'] = list(dict.fromkeys(hit['k'] + k)); continue
        rec = dict(t=r['t'], s=r['s'], u=r['u'], d=r['d'], k=k, sc=score(dict(r, k=k)), seen=now.strftime('%Y-%m-%d'))
        items.append(rec); urls.add(r['u']); sigs.append((w, rec)); added += 1
    items.sort(key=lambda i: i['d'], reverse=True)
    stats = {tp: sum(1 for i in items if tp in i['k']) for tp in TOPICS}
    since = (now - dt.timedelta(days=1)).strftime('%Y-%m-%dT%H:%MZ')
    arch = dict(as_of=now.strftime('%Y-%m-%d %H:%M UTC'), since=START.isoformat(), total=len(items), per_topic=stats,
                new_24h=sum(1 for i in items if i['d'] >= since), last_run=dict(requests=jobs, failed=fails, raw=len(raw), added=added,
                duplicates=dup, noise=dropped_noise, off_topic=dropped_off, backfill=backfill, lanes=stat), items=items)
    json.dump(arch, open(ARCH, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'added {added}  duplicates {dup}  noise {dropped_noise}  off-topic {dropped_off}  -> archive {len(items)} items since {START}')
    print('per topic', stats)
    return arch

def embed(arch, per_topic=40, cap=240):
    """Subset for the website snippet: newest per topic (balanced) + topic totals since 2025."""
    pick, seen = [], set()
    for tp in TOPICS:
        for i in [x for x in arch['items'] if tp in x['k']][:per_topic]:
            if i['u'] not in seen: seen.add(i['u']); pick.append(i)
    pick.sort(key=lambda i: i['d'], reverse=True)
    return dict(as_of=arch['as_of'], since=arch['since'], total=arch['total'], per_topic=arch['per_topic'], new_24h=arch['new_24h'], labels=LABEL,
                items=[dict(t=i['t'], s=i['s'], u=i['u'], d=i['d'][:16], k=i['k'], n=i.get('n', 1)) for i in pick[:cap]])

def index(arch):
    """Full searchable archive for the TSG Live Library (all items, compact rows: t, s, u, d, k, n)."""
    return dict(as_of=arch['as_of'], since=arch['since'], total=arch['total'], per_topic=arch['per_topic'], new_24h=arch['new_24h'], labels=LABEL,
                f=['t', 's', 'u', 'd', 'k', 'n'], items=[[i['t'], i['s'], i['u'], i['d'][:16], '|'.join(i['k']), i.get('n', 1)] for i in arch['items']])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--backfill', action='store_true'); a = ap.parse_args()
    arch = run(a.backfill)
    out = os.environ.get('TSG_NEWS_OUT') or os.path.join(HERE, 'out', 'tsg-news.json')
    json.dump(embed(arch), open(out, 'w'), ensure_ascii=False, separators=(',', ':'))
    json.dump(index(arch), open(os.path.join(os.path.dirname(out) or '.', 'tsg-news-index.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print('wrote', out, '+ tsg-news-index.json')
