import os
import sys
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import asyncio
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.auth_google import get_google_credentials
from googleapiclient.discovery import build

INDONESIAN_DOMAINS = 'kompas.com,bisnis.com,kontan.co.id,tempo.co,detik.com,republika.co.id'
EXECUTOR = ThreadPoolExecutor(max_workers=10)

SEARCH_TOPICS = [
    {
        "category": "Paper & Packaging",
        "time_window": "week",   # niche topic — cast a 7-day net
        "queries": [
            "waste paper OCC recovered fibre price Asia",
            "corrugated cardboard containerboard packaging industry",
            "paper pulp packaging market global",
            "global paper board packaging demand supply",
            "packaging industry e-commerce growth Asia",
            "kraft liner testliner recycled fibre price Europe",
            "cardboard box corrugated manufacturer news"
        ],
        "indonesian_query": "industri kertas kemasan harga OCC karton Indonesia"
    },
    {
        "category": "Wood & Timber",
        "time_window": "week",   # niche topic — cast a 7-day net
        "queries": [
            "MDF particleboard price global market",
            "plywood timber lumber market",
            "wood panel prices Asia global",
            "furniture manufacturing industry global news",
            "engineered wood OSB plywood demand supply",
            "timber lumber prices North America Europe",
            "wood products trade tariff export import"
        ],
        "indonesian_query": "industri kayu MDF papan partikel harga ekspor Indonesia"
    },
    {
        "category": "Indonesia Economy",
        "time_window": "today",  # top 10 from today only
        "queries": [
            "Indonesia rupiah exchange rate economy",
            "Indonesia GDP growth inflation consumer prices",
            "Bank Indonesia monetary policy interest rate",
            "Indonesia investment FDI Prabowo economic policy",
            "Indonesia manufacturing industry PMI output",
            "Indonesia government budget spending fiscal",
            "Indonesia trade balance export import surplus"
        ],
        "indonesian_query": "ekonomi Indonesia PDB inflasi investasi kebijakan moneter rupiah hari ini"
    },
    {
        "category": "Indonesia Finance & Banking",
        "time_window": "today",  # top 10 from today only
        "queries": [
            "Indonesia banking sector profit lending",
            "OJK Indonesia financial services regulation",
            "Indonesia capital market IDX stock IHSG",
            "Indonesia bank credit loan NPL",
            "Indonesia fintech digital banking regulation",
            "Indonesia insurance investment fund",
            "Bank Mestika regional bank Sumatra Indonesia"
        ],
        "indonesian_query": "perbankan Indonesia OJK keuangan kredit pasar modal IDX Bank Mestika hari ini"
    },
    {
        "category": "Southeast Asia Trade",
        "time_window": "today",  # top 10 from today only
        "queries": [
            "shipping container freight rates Asia Pacific",
            "Indonesia Malaysia Thailand export trade",
            "palm oil CPO price Indonesia Malaysia export",
            "Southeast Asia ASEAN trade agreement supply chain",
            "US China tariff trade war impact Southeast Asia",
            "Indonesia coal nickel mineral export",
            "ASEAN manufacturing supply chain China plus one"
        ],
        "indonesian_query": "perdagangan ekspor impor ASEAN kelapa sawit freight Indonesia Malaysia hari ini"
    },
    {
        "category": "Indonesia Today",
        "time_window": "today",  # top 10 from today only
        "queries": [
            "Indonesia news today politics economy",
            "Indonesia Prabowo government policy announcement",
            "Indonesia investment regulation business news today",
            "Jakarta Indonesia economy rupiah news today",
            "Indonesia stock market IDX IHSG latest",
            "Indonesia infrastructure development project",
            "Indonesia energy fuel electricity price subsidy"
        ],
        "indonesian_query": "berita terkini Indonesia ekonomi bisnis kebijakan pemerintah hari ini"
    },
    {
        "category": "Global Today",
        "time_window": "today",  # top 10 from today only
        "queries": [
            "global economy markets trade news today",
            "US China trade tariffs geopolitics",
            "Federal Reserve ECB interest rate inflation",
            "Asia Pacific economy business news today",
            "oil energy commodity prices global today",
            "global recession growth outlook IMF World Bank",
            "dollar yen euro currency markets today"
        ],
        "indonesian_query": "ekonomi global perdagangan dunia berita terkini hari ini"
    }
]


def search_news_google_rss(query, lang='en', country='US', time_window='week'):
    """Fetch articles from Google News RSS. No API key required.
    time_window: 'today' appends when:1d, 'week' appends when:7d.
    Note: Google News URLs are redirect-only and cannot be scraped for body text.
    Source name is appended to the title for Claude's context instead."""
    when = 'when:1d' if time_window == 'today' else 'when:7d'
    encoded = quote_plus(f"{query} {when}")
    ceid = f"{country}:{lang}"
    url = f"https://news.google.com/rss/search?q={encoded}&hl={lang}&gl={country}&ceid={ceid}"
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(resp.content)
        results = []
        for item in root.findall('./channel/item')[:8]:
            raw_title = item.findtext('title') or 'No title'
            source = item.findtext('source') or ''
            link = item.findtext('link') or ''
            pub_date = item.findtext('pubDate') or ''
            try:
                from email.utils import parsedate_to_datetime
                date_str = parsedate_to_datetime(pub_date).strftime('%Y-%m-%d')
            except Exception:
                date_str = datetime.now().strftime('%Y-%m-%d')
            # Include source name in title so Claude knows the publication
            title = f"{raw_title} [{source}]" if source else raw_title
            results.append({
                'title': title,
                'date': date_str,
                'url': link,
                'body': ''   # Google News URLs are not directly scrapeable
            })
        return results
    except Exception:
        return []


def search_news_newsapi(query, domains=None, time_window='week'):
    """Fallback: fetch articles from NewsAPI."""
    days = 1 if time_window == 'today' else 7
    from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q': query,
            'apiKey': os.getenv('NEWS_API_KEY'),
            'pageSize': 5,
            'sortBy': 'relevancy',
            'from': from_date,
        }
        if domains:
            params['domains'] = domains
        else:
            params['language'] = 'en'
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        results = []
        for article in data.get('articles', []):
            url_val = article.get('url', '')
            results.append({
                'title': article.get('title') or 'No title',
                'date': (article.get('publishedAt') or 'Unknown date')[:10],
                'url': url_val,
                'body': scrape_article_body(url_val) if url_val else ''
            })
        return results
    except Exception:
        return []


def search_news(query, domains=None, time_window='week'):
    """Primary: Google News RSS. Fallback: NewsAPI if RSS returns nothing."""
    print(f"  Searching: {query}" + (f" [domains]" if domains else ""))
    # For Indonesian domain queries, use Google News with Indonesia locale
    if domains:
        results = search_news_google_rss(query, lang='id', country='ID', time_window=time_window)
        if not results:
            results = search_news_newsapi(query, domains=domains, time_window=time_window)
    else:
        results = search_news_google_rss(query, time_window=time_window)
        if not results:
            results = search_news_newsapi(query, time_window=time_window)
    return results


def scrape_article_body(url):
    """Fetch article URL and extract main body text, stripping nav/footer/ads."""
    if not url or not url.startswith('http'):
        return ''
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return ''
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Remove noise elements
        for tag in soup.find_all(['nav', 'footer', 'header', 'aside', 'script',
                                   'style', 'noscript', 'iframe', 'figure']):
            tag.decompose()
        for tag in soup.find_all(class_=re.compile(r'ad|advertisement|sidebar|related|comment|social|share|cookie|popup', re.I)):
            tag.decompose()
        for tag in soup.find_all(id=re.compile(r'ad|sidebar|related|comment|social|share', re.I)):
            tag.decompose()

        # Try to find the main article content
        body = (soup.find('article') or
                soup.find('main') or
                soup.find(class_=re.compile(r'article[-_]?body|article[-_]?content|post[-_]?body|entry[-_]?content|story[-_]?body', re.I)) or
                soup.find('div', class_=re.compile(r'content|body|text', re.I)))

        text = (body or soup).get_text(separator=' ', strip=True)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception:
        return ''


def analyse_with_claude(category, articles, time_window='week'):
    """Send article headlines + body snippets to Claude for deep analysis."""
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    articles_text = ''
    for a in articles:
        body_snippet = a.get('body', '') or 'No body text available.'
        articles_text += f"- {a['title']} ({a['date']})\n  URL: {a.get('url','')}\n  Body: {body_snippet[:500]}\n\n"

    time_label = "today" if time_window == 'today' else "the past 7 days"
    count_instruction = "top 10 most important and distinct stories from today" if time_window == 'today' else "5-10 most relevant and distinct items from the past week (aim for at least 5)"

    prompt = f"""You are analysing market news for a family business group in Indonesia.

Business context:
- Hakarindo / Deli Corp: Corrugated packaging manufacturer across Sumatra and Java. Main raw material is waste paper/OCC. Key customers in furniture, food & beverage, e-commerce. Supplier to IKEA.
- Tjipta Group: Wood-based industries including MDF, particleboard, OSB, fingerjoint timber, furniture, resins.
- R6B Group: Palm oil plantations and refineries.
- Bank Mestika: Affiliated regional bank in Indonesia.
- All businesses affected by USD/IDR exchange rate as raw materials priced in USD.

Category: {category}

Recent articles (from {time_label}):
{articles_text}

Analyse these articles and return ONLY a JSON array of the {count_instruction}. Each item must have exactly these fields:
{{
    "headline": "most important headline in one sentence",
    "explanation": "2-3 paragraphs in plain English explaining what this news means and why it matters. Separate paragraphs with \\n\\n.",
    "hakarindo_impact": "specific operational or financial impact on Hakarindo / Deli Corp in 2-3 sentences",
    "tjipta_impact": "specific impact on Tjipta Group in 2-3 sentences",
    "r6b_impact": "specific impact on R6B Group in 2-3 sentences",
    "action": "concrete recommended next step for leadership in 2-3 sentences",
    "severity_score": <integer 1-10>,
    "severity_reason": "one sentence explaining the severity score",
    "urgency": "High or Medium or Watch",
    "source_urls": ["url1", "url2"],
    "article_date": "YYYY-MM-DD of the primary source article (use the actual article date, not today)"
}}

Use the article URLs and dates provided above. Return only the JSON array, no other text."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10000,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = message.content[0].text.strip()
    response_text = response_text.replace('```json', '').replace('```', '').strip()
    start = response_text.find('[')
    end = response_text.rfind(']') + 1
    if start == -1 or end == 0:
        print(f"  Warning: Could not find JSON array in Claude response for {category}")
        print(f"  Raw response: {response_text[:200]}")
        return [_fallback_item(category)]
    try:
        return json.loads(response_text[start:end])
    except json.JSONDecodeError:
        # Response may be truncated — recover any complete JSON objects before the cut-off
        partial = response_text[start:]
        recovered = []
        depth = 0
        obj_start = None
        for i, ch in enumerate(partial):
            if ch == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start is not None:
                    try:
                        recovered.append(json.loads(partial[obj_start:i+1]))
                    except json.JSONDecodeError:
                        pass
        if recovered:
            print(f"  Note: Recovered {len(recovered)} item(s) from partial response for {category}")
            return recovered
        print(f"  Warning: Could not parse response for {category}")
        return [_fallback_item(category)]


def _fallback_item(category):
    return {
        'headline': f'No analysis available for {category}',
        'explanation': 'Unable to parse news results.',
        'hakarindo_impact': '',
        'tjipta_impact': '',
        'r6b_impact': '',
        'action': '',
        'severity_score': 1,
        'severity_reason': 'Analysis unavailable.',
        'urgency': 'Watch',
        'source_urls': [],
        'article_date': ''
    }


def generate_editors_brief(deep_results: dict) -> str:
    """Synthesise a 2-sentence Editor's Brief from the 5 deep-analysis categories."""
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    lines = []
    for category, items in deep_results.items():
        top = [i for i in items if i.get('urgency') in ('High', 'HIGH')][:2] or items[:1]
        for item in top:
            lines.append(f"[{category}] {item.get('headline', '')}")
    prompt = (
        "Write exactly 2 sentences as an executive intelligence summary.\n\n"
        "Headlines:\n" + "\n".join(lines) + "\n\n"
        "Sentence 1: the dominant theme across today's news. "
        "Sentence 2: the 1-2 most urgent actions for leadership. "
        "Be specific. No JSON."
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


TRENDING_CATEGORIES = {'Indonesia Today', 'Global Today'}


def analyse_trending(category, articles):
    """Lighter analysis for trending news — headline + summary + source link only."""
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    articles_text = ''
    for a in articles:
        articles_text += f"- {a['title']} ({a['date']})\n  URL: {a.get('url','')}\n\n"

    prompt = f"""You are summarising today's most important news for Indonesian business executives.

Category: {category}

Recent articles (from today):
{articles_text}

Return ONLY a JSON array of the top 10 most newsworthy items from today. Each item must have exactly these fields:
{{
    "headline": "clear headline in one sentence",
    "explanation": "2-3 sentences explaining what happened and why it matters to Indonesian businesses.",
    "hakarindo_impact": "",
    "tjipta_impact": "",
    "r6b_impact": "",
    "action": "",
    "severity_score": <integer 1-5>,
    "severity_reason": "one sentence",
    "urgency": "Watch",
    "source_urls": ["url1"],
    "article_date": "YYYY-MM-DD of the primary source article (use the actual article date, not today)"
}}

Use the article URLs and dates provided above. Return only the JSON array, no other text."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10000,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = message.content[0].text.strip()
    response_text = response_text.replace('```json', '').replace('```', '').strip()
    start = response_text.find('[')
    end = response_text.rfind(']') + 1
    if start == -1 or end == 0:
        print(f"  Warning: Could not find JSON array in Claude response for {category}")
        return [_fallback_item(category)]
    try:
        return json.loads(response_text[start:end])
    except json.JSONDecodeError:
        partial = response_text[start:]
        recovered = []
        depth = 0
        obj_start = None
        for i, ch in enumerate(partial):
            if ch == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start is not None:
                    try:
                        recovered.append(json.loads(partial[obj_start:i+1]))
                    except json.JSONDecodeError:
                        pass
        if recovered:
            return recovered
        return [_fallback_item(category)]


async def fetch_topic_articles(topic: dict, loop) -> tuple:
    """Run all search_news() calls for one topic concurrently in the thread pool."""
    category = topic['category']
    time_window = topic.get('time_window', 'week')
    search_tasks = [
        loop.run_in_executor(EXECUTOR, search_news, q, None, time_window)
        for q in topic['queries']
    ]
    search_tasks.append(
        loop.run_in_executor(
            EXECUTOR, search_news,
            topic.get('indonesian_query', f"{category} Indonesia"),
            INDONESIAN_DOMAINS, time_window
        )
    )
    results = await asyncio.gather(*search_tasks)
    all_articles = [art for batch in results for art in batch]
    return category, all_articles, time_window


async def analyse_topic_async(topic: dict, loop) -> tuple:
    """Fetch articles then call Claude for one category — fully pipelined."""
    category, all_articles, time_window = await fetch_topic_articles(topic, loop)
    print(f"  [{category}] {len(all_articles)} articles — analysing...")
    if category in TRENDING_CATEGORIES:
        analysis = await loop.run_in_executor(
            EXECUTOR, analyse_trending, category, all_articles
        )
    else:
        analysis = await loop.run_in_executor(
            EXECUTOR, analyse_with_claude, category, all_articles, time_window
        )
    return category, analysis


async def run_briefing_async():
    date_str = datetime.now().strftime('%Y-%m-%d')
    print(f"\n=== Tjipta Intelligence Briefing: {date_str} ===\n")
    loop = asyncio.get_running_loop()

    deep_topics = [t for t in SEARCH_TOPICS if t['category'] not in TRENDING_CATEGORIES]
    trending_topics = [t for t in SEARCH_TOPICS if t['category'] in TRENDING_CATEGORIES]

    # Phase 1: all 7 categories run concurrently
    all_tasks = [analyse_topic_async(t, loop) for t in deep_topics + trending_topics]
    topic_results = await asyncio.gather(*all_tasks)

    all_results = {}
    deep_results = {}
    for category, analysis in topic_results:
        all_results[category] = analysis
        if category not in TRENDING_CATEGORIES:
            deep_results[category] = analysis

    # Phase 2: synthesis — runs after all deep analysis is complete
    print("\n[Synthesis] Writing Editor's Brief...")
    editors_brief = await loop.run_in_executor(
        EXECUTOR, generate_editors_brief, deep_results
    )
    print(f"  Editor's Brief: {editors_brief[:80]}...")

    write_to_sheet(all_results, date_str)
    write_data_js(all_results, date_str, editors_brief)
    print(f"\n=== Briefing Complete ({date_str}) ===")


def write_to_sheet(all_results, date_str):
    print("Writing to Google Sheet...")
    creds = get_google_credentials()
    service = build('sheets', 'v4', credentials=creds)
    sheet_id = os.getenv('GOOGLE_SHEET_ID')
    tab = 'Morning Briefing'

    headers = ['Date', 'Category', 'Headline', 'Explanation',
               'Hakarindo Impact', 'Tjipta Impact', 'R6B Impact',
               'Action', 'Severity Score', 'Severity Reason', 'Urgency', 'Source URLs']

    sheet_meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing_tabs = [s['properties']['title'] for s in sheet_meta['sheets']]

    if tab not in existing_tabs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': tab}}}]}
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{tab}'!A1:L1",
            valueInputOption='RAW',
            body={'values': [headers]}
        ).execute()
    else:
        existing = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"'{tab}'!A1:L1"
        ).execute()
        if not existing.get('values'):
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"'{tab}'!A1:L1",
                valueInputOption='RAW',
                body={'values': [headers]}
            ).execute()

    rows = []
    for category, items in all_results.items():
        for item in items:
            source_urls_str = ','.join(item.get('source_urls', []))
            rows.append([
                item.get('article_date') or date_str,
                category,
                item.get('headline', ''),
                item.get('explanation', ''),
                item.get('hakarindo_impact', ''),
                item.get('tjipta_impact', ''),
                item.get('r6b_impact', ''),
                item.get('action', ''),
                item.get('severity_score', 1),
                item.get('severity_reason', ''),
                item.get('urgency', 'Watch'),
                source_urls_str
            ])

    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"'{tab}'!A:L",
        valueInputOption='RAW',
        body={'values': rows}
    ).execute()
    print(f"Written {len(rows)} rows to Google Sheet (12 columns A-L).")


def fetch_live_prices():
    """Fetch gold and Brent crude server-side (no CORS issues in Python)."""
    prices = {}
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://goldprice.org/'
        }
        resp = requests.get('https://data-asg.goldprice.org/dbXRates/USD', headers=headers, timeout=8)
        data = resp.json()
        gold = next((i['xauPrice'] for i in data.get('items', []) if i.get('curr') == 'USD'), None)
        if gold:
            prices['gold'] = round(gold)
    except Exception:
        pass
    try:
        resp = requests.get(
            'https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?interval=1d&range=1d',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        data = resp.json()
        price = data['chart']['result'][0]['meta']['regularMarketPrice']
        prices['brent'] = round(price, 2)
    except Exception:
        pass
    # BI Rate — scraped from Trading Economics (updates after each Bank Indonesia meeting)
    try:
        resp = requests.get(
            'https://tradingeconomics.com/indonesia/interest-rate',
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml'
            }, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = re.sub(r'\s+', ' ', soup.get_text(separator=' '))
        m = re.search(r'(\d+\.\d+)\s*percent', text)
        if m:
            prices['bi_rate'] = float(m.group(1))
    except Exception:
        pass
    # Methanex Asia Pacific posted price — industry reference for Indonesian market (monthly)
    try:
        resp = requests.get(
            'https://www.methanex.com/our-business/pricing/',
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml'
            }, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = soup.get_text(separator=' ')
        text = re.sub(r'\s+', ' ', text)
        # Find Asia Pacific section and extract USD xxx/MT value
        asia_match = re.search(r'Asia Pacific.*?USD\s+(\d{2,4})/MT', text)
        if asia_match:
            prices['methanol'] = float(asia_match.group(1))
    except Exception:
        pass
    return prices


def write_data_js(all_results, date_str, editors_brief=''):
    """Write today's briefing data as a local JS file so the dashboard loads it without CORS issues."""
    items = []
    idx = 1
    for category, analysis in all_results.items():
        for item in analysis:
            source_urls = item.get('source_urls', [])
            if isinstance(source_urls, str):
                source_urls = [u.strip() for u in source_urls.split(',') if u.strip()]
            explanation = item.get('explanation', '')
            items.append({
                'id': idx,
                'date': item.get('article_date') or date_str,
                'cat': category,
                'h': item.get('headline', ''),
                'explanation': explanation,
                'hakarindo_impact': item.get('hakarindo_impact', ''),
                'tjipta_impact': item.get('tjipta_impact', ''),
                'r6b_impact': item.get('r6b_impact', ''),
                'action': item.get('action', ''),
                'severity_score': int(float(item.get('severity_score', 5) or 5)),
                'severity_reason': item.get('severity_reason', ''),
                'u': item.get('urgency', 'Watch'),
                'source_urls': source_urls,
                'preview': (explanation or item.get('headline', ''))[:120] + '…'
            })
            idx += 1
    prices = fetch_live_prices()
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data.js')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('window.BRIEFING_DATA = ')
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write(';\n')
        f.write('window.LIVE_PRICES = ')
        json.dump({'gold': prices.get('gold'), 'brent': prices.get('brent'), 'methanol': prices.get('methanol'), 'bi_rate': prices.get('bi_rate'), 'updated': date_str}, f)
        f.write(';\n')
        f.write('window.EDITORS_BRIEF = ')
        json.dump(editors_brief, f, ensure_ascii=False)
        f.write(';\n')
    print(f"Written {len(items)} items + live prices to data.js for dashboard.")
    push_data_js_to_github(out_path)


def push_to_github(file_path, content_bytes, commit_msg):
    """Push a single file to the GitHub repo via API."""
    import base64
    token = os.getenv('GITHUB_TOKEN')
    repo = os.getenv('GITHUB_REPO')
    if not token or not repo:
        return False
    headers = {'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'}
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    r = requests.get(api_url, headers=headers, timeout=10)
    sha = r.json().get('sha', '') if r.status_code == 200 else ''
    payload = {'message': commit_msg, 'content': base64.b64encode(content_bytes).decode()}
    if sha:
        payload['sha'] = sha
    r = requests.put(api_url, headers=headers, json=payload, timeout=15)
    return r.status_code in (200, 201)


def push_data_js_to_github(local_data_js_path):
    """Push data.js and index.html to GitHub so the hosted dashboard stays fresh."""
    token = os.getenv('GITHUB_TOKEN')
    repo = os.getenv('GITHUB_REPO')
    if not token or not repo:
        print("  Skipping GitHub push (GITHUB_TOKEN or GITHUB_REPO not set in .env).")
        return
    date_str = datetime.now().strftime('%Y-%m-%d')
    try:
        # Push data.js
        with open(local_data_js_path, 'rb') as f:
            ok = push_to_github('data.js', f.read(), f'Update briefing data ({date_str})')
        print(f"  data.js {'pushed' if ok else 'push FAILED'} → GitHub ({repo}).")
        # Push index.html (keeps hosted page in sync with local edits)
        html_path = os.path.join(os.path.dirname(local_data_js_path), 'index.html')
        if os.path.exists(html_path):
            with open(html_path, 'rb') as f:
                ok2 = push_to_github('index.html', f.read(), f'Update dashboard ({date_str})')
            print(f"  index.html {'pushed' if ok2 else 'push FAILED'} → GitHub ({repo}).")
    except Exception as e:
        print(f"  GitHub push error: {e}")


def run_briefing():
    asyncio.run(run_briefing_async())


if __name__ == '__main__':
    run_briefing()
