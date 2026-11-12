"""Rule-based use-case extractor (no LLM) – used by the unattended GitHub Actions agent.
Takes scouted headlines -> keeps only concrete deployments by a named organisation with a resolvable location.
Strict: org = words before the deployment verb; location = known org HQ, else a city/country named in the headline.
"""
import re

VERB = (r'\b(launch(es|ed)?|pilots?|piloted|deploy(s|ed)?|rolls? out|rolled out|goes live|went live|go live|issues?|issued|unveils?|unveiled|'
        r'completes?|completed|debuts?|introduces?|introduced|selects?|taps|tapped|partners with|teams up with|expands?|adopts?|implements?|tokeni[sz]es|settles?)\b')
STATUS = [(r'pilot|trial|test|sandbox|proof of concept|poc\b', 'Pilot'), (r'goes live|went live|go live|launch|deploy|rolls? out|rolled out|issued?|completes?|debut|settles?|implements?|adopts?', 'Production')]
SECTOR = [(r'bank|fund|bond|payment|stablecoin|treasur|asset manag|securit|deposit|exchange|insur|credit|money[- ]market|tokeni', 'Finance'),
          (r'hospital|health|clinic|patient|pharma|medical|drug|biotech', 'Healthcare'),
          (r'factory|manufactur|industrial|plant|machin|predictive maintenance|robot', 'Manufacturing'),
          (r'logistic|supply chain|shipping|port\b|freight|container|cold chain|warehouse', 'Logistics & Supply Chain'),
          (r'energy|grid|utility|solar|power|oil|gas\b|carbon', 'Energy & Utilities'),
          (r'farm|agri|food|crop', 'Agriculture & Food'), (r'real estate|property|housing', 'Real Estate'),
          (r'retail|luxury|commerce|shop|consumer', 'Luxury & Retail'), (r'city|government|ministry|public|army|defen[cs]e|universit|research', 'Public Sector & Research'),
          (r'car\b|vehicle|mobility|automotive|airline|aviation|rail', 'Mobility')]
TECH = {'RWA': r'tokeni[sz]|real[- ]world asset|\brwa\b|on-?chain (fund|bond|treasur)|digital bond|money[- ]market fund',
        'Blockchain': r'blockchain|ledger|stablecoin|\bcbdc\b|on-?chain|ethereum|solana|avalanche|polygon|hedera|smart contract|tokenized deposit',
        'Agentic': r'agentic|ai agents?|autonomous agents?|multi-agent|agentforce',
        'IoT': r'\biot\b|iiot|internet of things|\bsensors?\b|digital twin|connected (devices?|cars?|vehicles?)|telematics|predictive maintenance|\bedge (ai|computing)',
        'AI': r'\bai\b|artificial intelligence|machine learning|generative|genai|\bllm'}
# well-known organisation HQs (lat, lon, city, ISO-2)
ORG = {
 'JPMorgan': (40.7128, -74.006, 'New York', 'US'), 'J.P. Morgan': (40.7128, -74.006, 'New York', 'US'), 'Kinexys': (40.7128, -74.006, 'New York', 'US'),
 'BlackRock': (40.7128, -74.006, 'New York', 'US'), 'Goldman Sachs': (40.7128, -74.006, 'New York', 'US'), 'Citi': (40.7128, -74.006, 'New York', 'US'),
 'Morgan Stanley': (40.7128, -74.006, 'New York', 'US'), 'BNY': (40.7128, -74.006, 'New York', 'US'), 'NYSE': (40.7069, -74.0113, 'New York', 'US'),
 'Nasdaq': (40.7128, -74.006, 'New York', 'US'), 'Mastercard': (41.0339, -73.7629, 'Purchase, NY', 'US'), 'Visa': (37.5585, -122.2711, 'San Francisco', 'US'),
 'PayPal': (37.3688, -121.9254, 'San Jose', 'US'), 'Franklin Templeton': (37.5630, -122.3255, 'San Mateo', 'US'), 'Fidelity': (42.3601, -71.0589, 'Boston', 'US'),
 'State Street': (42.3601, -71.0589, 'Boston', 'US'), 'Apollo': (40.7128, -74.006, 'New York', 'US'), 'WisdomTree': (40.7128, -74.006, 'New York', 'US'),
 'Securitize': (25.7617, -80.1918, 'Miami', 'US'), 'Circle': (40.7128, -74.006, 'New York', 'US'), 'Coinbase': (37.7749, -122.4194, 'San Francisco', 'US'),
 'Ripple': (37.7749, -122.4194, 'San Francisco', 'US'), 'Ondo': (40.7128, -74.006, 'New York', 'US'), 'Chainlink': (37.7749, -122.4194, 'San Francisco', 'US'),
 "Moody's": (40.7128, -74.006, 'New York', 'US'), 'S&P Global': (40.7128, -74.006, 'New York', 'US'), 'Fitch': (40.7128, -74.006, 'New York', 'US'), 'DTCC': (40.7128, -74.006, 'New York', 'US'),
 'PNC': (40.4406, -79.9959, 'Pittsburgh', 'US'), 'Bank of America': (35.2271, -80.8431, 'Charlotte', 'US'), 'Wells Fargo': (37.7749, -122.4194, 'San Francisco', 'US'),
 'Microsoft': (47.674, -122.1215, 'Redmond', 'US'), 'Google': (37.422, -122.0841, 'Mountain View', 'US'), 'Alphabet': (37.422, -122.0841, 'Mountain View', 'US'),
 'Amazon': (47.6062, -122.3321, 'Seattle', 'US'), 'AWS': (47.6062, -122.3321, 'Seattle', 'US'), 'Salesforce': (37.7749, -122.4194, 'San Francisco', 'US'),
 'IBM': (41.1084, -73.7204, 'Armonk', 'US'), 'Oracle': (30.2672, -97.7431, 'Austin', 'US'), 'Nvidia': (37.3541, -121.9552, 'Santa Clara', 'US'),
 'Intel': (37.3541, -121.9552, 'Santa Clara', 'US'), 'Cisco': (37.3382, -121.8863, 'San Jose', 'US'), 'ServiceNow': (37.3541, -121.9552, 'Santa Clara', 'US'),
 'OpenAI': (37.7749, -122.4194, 'San Francisco', 'US'), 'Anthropic': (37.7749, -122.4194, 'San Francisco', 'US'), 'Meta': (37.4848, -122.1484, 'Menlo Park', 'US'),
 'Apple': (37.3349, -122.009, 'Cupertino', 'US'), 'Walmart': (36.3729, -94.2088, 'Bentonville', 'US'), 'Deloitte': (51.5074, -0.1278, 'London', 'GB'),
 'Accenture': (53.3498, -6.2603, 'Dublin', 'IE'), 'UBS': (47.3769, 8.5417, 'Zurich', 'CH'), 'SIX': (47.3769, 8.5417, 'Zurich', 'CH'),
 'Swisscom': (46.948, 7.4474, 'Bern', 'CH'), 'Zurich Insurance': (47.3769, 8.5417, 'Zurich', 'CH'), 'Julius Baer': (47.3769, 8.5417, 'Zurich', 'CH'),
 'Sygnum': (47.3769, 8.5417, 'Zurich', 'CH'), 'AMINA': (47.1662, 8.5155, 'Zug', 'CH'), 'SEBA': (47.1662, 8.5155, 'Zug', 'CH'), 'Taurus': (46.2044, 6.1432, 'Geneva', 'CH'),
 'Pictet': (46.2044, 6.1432, 'Geneva', 'CH'), 'ABB': (47.3769, 8.5417, 'Zurich', 'CH'), 'Nestlé': (46.4628, 6.8419, 'Vevey', 'CH'), 'Nestle': (46.4628, 6.8419, 'Vevey', 'CH'),
 'Novartis': (47.5596, 7.5886, 'Basel', 'CH'), 'Roche': (47.5596, 7.5886, 'Basel', 'CH'), 'PostFinance': (46.948, 7.4474, 'Bern', 'CH'), 'SNB': (46.948, 7.4474, 'Bern', 'CH'),
 'HSBC': (51.5074, -0.1278, 'London', 'GB'), 'Barclays': (51.5074, -0.1278, 'London', 'GB'), 'Standard Chartered': (51.5074, -0.1278, 'London', 'GB'),
 'Lloyds': (51.5074, -0.1278, 'London', 'GB'), 'LSEG': (51.5074, -0.1278, 'London', 'GB'), 'Schroders': (51.5074, -0.1278, 'London', 'GB'),
 'abrdn': (55.9533, -3.1883, 'Edinburgh', 'GB'), 'Siemens': (48.1351, 11.582, 'Munich', 'DE'), 'Deutsche Bank': (50.1109, 8.6821, 'Frankfurt', 'DE'),
 'Commerzbank': (50.1109, 8.6821, 'Frankfurt', 'DE'), 'Deutsche Börse': (50.1109, 8.6821, 'Frankfurt', 'DE'), 'Bosch': (48.7758, 9.1829, 'Stuttgart', 'DE'),
 'SAP': (49.2933, 8.6417, 'Walldorf', 'DE'), 'Allianz': (48.1351, 11.582, 'Munich', 'DE'), 'BMW': (48.1351, 11.582, 'Munich', 'DE'), 'Mercedes': (48.7758, 9.1829, 'Stuttgart', 'DE'),
 'Volkswagen': (52.4227, 10.7865, 'Wolfsburg', 'DE'), 'BNP Paribas': (48.8566, 2.3522, 'Paris', 'FR'), 'Societe Generale': (48.8566, 2.3522, 'Paris', 'FR'),
 'Société Générale': (48.8566, 2.3522, 'Paris', 'FR'), 'SG Forge': (48.8566, 2.3522, 'Paris', 'FR'), 'AXA': (48.8566, 2.3522, 'Paris', 'FR'),
 'Santander': (40.4168, -3.7038, 'Madrid', 'ES'), 'BBVA': (43.263, -2.935, 'Bilbao', 'ES'), 'ING': (52.3676, 4.9041, 'Amsterdam', 'NL'), 'ABN AMRO': (52.3676, 4.9041, 'Amsterdam', 'NL'),
 'Euroclear': (50.8503, 4.3517, 'Brussels', 'BE'), 'Clearstream': (49.6116, 6.1319, 'Luxembourg', 'LU'), 'Maersk': (55.6761, 12.5683, 'Copenhagen', 'DK'),
 'DBS': (1.3521, 103.8198, 'Singapore', 'SG'), 'OCBC': (1.3521, 103.8198, 'Singapore', 'SG'), 'UOB': (1.3521, 103.8198, 'Singapore', 'SG'), 'MAS': (1.3521, 103.8198, 'Singapore', 'SG'),
 'Grab': (1.3521, 103.8198, 'Singapore', 'SG'), 'HKMA': (22.3193, 114.1694, 'Hong Kong', 'HK'), 'HashKey': (22.3193, 114.1694, 'Hong Kong', 'HK'),
 'Ant Group': (30.2741, 120.1551, 'Hangzhou', 'CN'), 'Alibaba': (30.2741, 120.1551, 'Hangzhou', 'CN'), 'Tencent': (22.5431, 114.0579, 'Shenzhen', 'CN'),
 'Huawei': (22.5431, 114.0579, 'Shenzhen', 'CN'), 'Sony': (35.6762, 139.6503, 'Tokyo', 'JP'), 'MUFG': (35.6762, 139.6503, 'Tokyo', 'JP'), 'SBI': (35.6762, 139.6503, 'Tokyo', 'JP'),
 'Toyota': (35.0824, 137.1563, 'Toyota City', 'JP'), 'Mizuho': (35.6762, 139.6503, 'Tokyo', 'JP'), 'Samsung': (37.2636, 127.0286, 'Suwon', 'KR'), 'Hyundai': (37.5665, 126.978, 'Seoul', 'KR'),
 'Emirates NBD': (25.2048, 55.2708, 'Dubai', 'AE'), 'DMZ Finance': (25.2048, 55.2708, 'Dubai', 'AE'), 'QNB': (25.2854, 51.531, 'Doha', 'QA'),
 'Infosys': (12.9716, 77.5946, 'Bengaluru', 'IN'), 'TCS': (19.076, 72.8777, 'Mumbai', 'IN'), 'Reliance': (19.076, 72.8777, 'Mumbai', 'IN'), 'HDFC': (19.076, 72.8777, 'Mumbai', 'IN'),
 'ANZ': (-37.8136, 144.9631, 'Melbourne', 'AU'), 'Commonwealth Bank': (-33.8688, 151.2093, 'Sydney', 'AU'), 'Westpac': (-33.8688, 151.2093, 'Sydney', 'AU'),
 'RBC': (43.6532, -79.3832, 'Toronto', 'CA'), 'TD': (43.6532, -79.3832, 'Toronto', 'CA'), 'Binance': (25.2048, 55.2708, 'Dubai', 'AE'), 'Tether': (8.9824, -79.5199, 'San Salvador', 'SV'),
}
PLACE = {  # city / country names that may appear in a headline
 'New York': (40.7128, -74.006, 'US'), 'San Francisco': (37.7749, -122.4194, 'US'), 'Chicago': (41.8781, -87.6298, 'US'), 'Texas': (30.2672, -97.7431, 'US'),
 'London': (51.5074, -0.1278, 'GB'), 'UK': (51.5074, -0.1278, 'GB'), 'Britain': (51.5074, -0.1278, 'GB'), 'Zurich': (47.3769, 8.5417, 'CH'), 'Zug': (47.1662, 8.5155, 'CH'),
 'Geneva': (46.2044, 6.1432, 'CH'), 'Swiss': (46.948, 7.4474, 'CH'), 'Switzerland': (46.948, 7.4474, 'CH'), 'Liechtenstein': (47.141, 9.5209, 'LI'),
 'Germany': (52.52, 13.405, 'DE'), 'German': (52.52, 13.405, 'DE'), 'Frankfurt': (50.1109, 8.6821, 'DE'), 'Berlin': (52.52, 13.405, 'DE'), 'Munich': (48.1351, 11.582, 'DE'),
 'France': (48.8566, 2.3522, 'FR'), 'French': (48.8566, 2.3522, 'FR'), 'Paris': (48.8566, 2.3522, 'FR'), 'Spain': (40.4168, -3.7038, 'ES'), 'Madrid': (40.4168, -3.7038, 'ES'),
 'Italy': (41.9028, 12.4964, 'IT'), 'Italian': (41.9028, 12.4964, 'IT'), 'Netherlands': (52.3676, 4.9041, 'NL'), 'Dutch': (52.3676, 4.9041, 'NL'), 'Luxembourg': (49.6116, 6.1319, 'LU'),
 'Belgium': (50.8503, 4.3517, 'BE'), 'Austria': (48.2082, 16.3738, 'AT'), 'Sweden': (59.3293, 18.0686, 'SE'), 'Norway': (59.9139, 10.7522, 'NO'), 'Denmark': (55.6761, 12.5683, 'DK'),
 'Finland': (60.1699, 24.9384, 'FI'), 'Poland': (52.2297, 21.0122, 'PL'), 'Ireland': (53.3498, -6.2603, 'IE'), 'Portugal': (38.7223, -9.1393, 'PT'),
 'Singapore': (1.3521, 103.8198, 'SG'), 'Hong Kong': (22.3193, 114.1694, 'HK'), 'China': (39.9042, 116.4074, 'CN'), 'Chinese': (39.9042, 116.4074, 'CN'), 'Shanghai': (31.2304, 121.4737, 'CN'),
 'Japan': (35.6762, 139.6503, 'JP'), 'Japanese': (35.6762, 139.6503, 'JP'), 'Tokyo': (35.6762, 139.6503, 'JP'), 'Korea': (37.5665, 126.978, 'KR'), 'Korean': (37.5665, 126.978, 'KR'),
 'Seoul': (37.5665, 126.978, 'KR'), 'Taiwan': (25.033, 121.5654, 'TW'), 'India': (28.6139, 77.209, 'IN'), 'Indian': (28.6139, 77.209, 'IN'), 'Mumbai': (19.076, 72.8777, 'IN'),
 'Thailand': (13.7563, 100.5018, 'TH'), 'Vietnam': (21.0278, 105.8342, 'VN'), 'Indonesia': (-6.2088, 106.8456, 'ID'), 'Malaysia': (3.139, 101.6869, 'MY'), 'Philippines': (14.5995, 120.9842, 'PH'),
 'Australia': (-33.8688, 151.2093, 'AU'), 'Australian': (-33.8688, 151.2093, 'AU'), 'New Zealand': (-41.2865, 174.7762, 'NZ'),
 'Dubai': (25.2048, 55.2708, 'AE'), 'Abu Dhabi': (24.4539, 54.3773, 'AE'), 'UAE': (24.4539, 54.3773, 'AE'), 'Saudi': (24.7136, 46.6753, 'SA'), 'Qatar': (25.2854, 51.531, 'QA'),
 'Bahrain': (26.0667, 50.5577, 'BH'), 'Israel': (32.0853, 34.7818, 'IL'), 'Turkey': (41.0082, 28.9784, 'TR'), 'Nigeria': (6.5244, 3.3792, 'NG'), 'Kenya': (-1.2921, 36.8219, 'KE'),
 'South Africa': (-26.2041, 28.0473, 'ZA'), 'Brazil': (-23.5505, -46.6333, 'BR'), 'Brazilian': (-23.5505, -46.6333, 'BR'), 'Mexico': (19.4326, -99.1332, 'MX'),
 'Argentina': (-34.6037, -58.3816, 'AR'), 'Chile': (-33.4489, -70.6693, 'CL'), 'Colombia': (4.711, -74.0721, 'CO'), 'Canada': (43.6532, -79.3832, 'CA'), 'Canadian': (43.6532, -79.3832, 'CA'),
}

CITIES = {'New York', 'San Francisco', 'Chicago', 'London', 'Zurich', 'Zug', 'Geneva', 'Frankfurt', 'Berlin', 'Munich', 'Paris', 'Madrid', 'Singapore', 'Hong Kong', 'Shanghai', 'Tokyo', 'Seoul', 'Mumbai', 'Dubai', 'Abu Dhabi', 'Luxembourg'}

def _find(d, title):
    for k in sorted(d, key=len, reverse=True):
        if re.search(r'(?<![A-Za-z])' + re.escape(k) + r'(?![A-Za-z])', title): return k
    return None

def extract(c):
    t = c['title'].strip()
    m = re.search(VERB, t, re.I)
    if not m or m.start() < 2: return None
    org = re.split(r'[:|–—]|\s-\s', t[:m.start()])[-1].strip(" ,'’\"")
    org = re.sub(r'\s+(to|will|is set to|set to|plans to|aims to|has|have|is|are|and|now|officially|quietly|reportedly)$', '', org, flags=re.I).strip()
    org = re.sub(r'\s+(to|will|set to|plans to)$', '', org, flags=re.I).strip()
    w = org.split()
    if not (1 <= len(w) <= 6) or not org[0].isupper() or re.match(r'(How|Why|What|When|Will|Can|The|This|These|New|A|An|Report|Study)\b', org): return None
    tech = [k for k, rx in TECH.items() if re.search(rx, t, re.I)]
    if not tech: return None
    if 'Agentic' in tech and 'AI' in tech: tech.remove('AI')
    k = _find(ORG, org); p = None if k else _find(PLACE, t)
    if not k and not p: k = _find(ORG, t)
    if k: lat, lon, city, cc = ORG[k]
    elif p: lat, lon, cc = PLACE[p]; city = p if p in CITIES else ''
    else: return None
    status = next((s for rx, s in STATUS if re.search(rx, t, re.I)), 'Announced')
    sector = next((s for rx, s in SECTOR if re.search(rx, t, re.I)), 'Cross-industry')
    rest = t[m.start():]; rest = rest[:1].lower() + rest[1:] if not rest[:2].isupper() else rest
    title = org + ' – ' + rest
    if len(title) > 120: title = title[:117].rsplit(' ', 1)[0] + '…'
    return dict(title=title, org=org, tech=tech, sector=sector, status=status, city=city or '', country=cc, lat=lat, lon=lon,
                kpi=t[m.start():][:1].upper() + t[m.start():][1:160])
