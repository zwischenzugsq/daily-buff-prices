"""Refresh reviewed public price identities. Stdlib only; no private services.

Run from this directory. Network is bounded, serial and stops on source errors.
Unchanged identity is mandatory; old observations never receive fresh dates.
"""
import copy, datetime as dt, gzip, hashlib, html, io, json, math, os, re, time
import urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = 'cyprus-prices-weekly-v1'
UA = 'TheDailyBuff-price-refresh/1.0 (https://github.com/zwischenzugsq/daily-buff-prices)'
HOSTS = {'www.e-kalathi.gov.cy', 'cdn.alphamega.com.cy', 'search.unbxd.io', 'www.metro.com.cy'}
CATALOGUE = 'https://www.e-kalathi.gov.cy/ekalathi-website-server/api/fetch-product-list?page=0&size=500&sort=DEFAULT,ASC'
ALPHA_CONFIG = 'https://cdn.alphamega.com.cy/Files/Templates/Designs/Swift/Assets/js/custom.js'
METRO = 'https://www.metro.com.cy/en/current_offers'

def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def clean(s): return re.sub(r'\s+', ' ', html.unescape(str(s or ''))).strip()
def barcode(s):
    s=str(s)
    if not s.isdigit() or len(s) not in (8,12,13,14): return None
    if sum(int(n)*(3 if i%2==0 else 1) for i,n in enumerate(reversed(s[:-1])))%10 != (-int(s[-1]))%10:return None
    return s.zfill(14)
def retailer(s):
    s=clean(s)
    if s=='ΑΛΦΑΜΕΓΑ': return 'Alphamega'
    if s.startswith('ΑΘΗΑΙΝΙΤΗΣ'): return 'Athienitis'
    if s=='ΣΚΛΑΒΕΝΙΤΗΣ': return 'Sklavenitis'
    if s=='LIDL': return 'Lidl'
    if s.startswith('SMART DISCOUNT SHOP'): return 'Smart Discount Shop'
    if s=='WOLT MARKET': return 'Wolt Market'
    return s

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('Source redirected; review required')

class Fetcher:
    def __init__(self): self.last=0; self.count=0
    def get(self,url,delay=2,as_json=True):
        u=urllib.parse.urlparse(url)
        if u.scheme!='https' or u.hostname not in HOSTS or u.username or u.password: raise ValueError('Unapproved source')
        self.count+=1
        if self.count>420: raise ValueError('Request limit reached')
        time.sleep(max(0,delay-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        request=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'gzip'})
        # Do not print exceptions containing search client configuration URLs.
        with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:
            body=response.read(40_000_001)
            if len(body)>40_000_000: raise ValueError('Response too large')
            if response.headers.get('Content-Encoding')=='gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz: body=gz.read(40_000_001)
            if len(body)>40_000_000: raise ValueError('Expanded response too large')
        return json.loads(body) if as_json else body.decode('utf-8')

def keyed(products):
    result={}
    for p in products:
        key=(p['source'],str(p['sourceProductId']))
        if key in result: raise ValueError('Duplicate source product')
        result[key]=p
    return result

def validate(book, seed):
    if book.get('encoding')!='by-product-v1' or len(book['products'])>1000: raise ValueError('Invalid encoding/size')
    if book['shops']!=seed['shops']: raise ValueError('Shop identities changed')
    expected=keyed(seed['products']); current=keyed(book['products'])
    if current.keys()!=expected.keys(): raise ValueError('Product identities changed')
    shops={s['id'] for s in seed['shops']}
    for key,p in current.items():
        original=expected[key]
        for field in set(p)|set(original):
            if field not in {'prices','observedAt','inStock','validUntil'} and p.get(field)!=original.get(field): raise ValueError('Product metadata changed')
        when=dt.datetime.fromisoformat(p['observedAt'])
        if when.tzinfo is None or when>dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5):raise ValueError('Invalid collection date')
        seen=set()
        for shop,price in p['prices']:
            if shop not in shops or shop in seen or type(price) not in (int,float) or not math.isfinite(price) or price<=0: raise ValueError('Invalid/duplicate branch price')
            seen.add(shop)

def checked_price(value, previous):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid price')
    if abs(value*100-round(value*100))>.0001:raise ValueError('Fractional cent')
    if previous is not None and not .5<=value/previous<=2:raise ValueError('Large price change needs review')
    return round(value,2)

def refresh_kalathi(fetch, book, report):
    catalogue=fetch.get(CATALOGUE)
    rows=catalogue['content']
    if catalogue.get('totalPages',1)!=1 or len(rows)!=catalogue['totalElements'] or len(rows)>500:raise ValueError('Incomplete catalogue')
    products={str(p['productMasterId']):p for p in rows}
    if len(products)!=len(rows):raise ValueError('Duplicate catalogue identity')
    shops={s['id']:s for s in book['shops']}
    for p in book['products']:
        if p['source']!='ekalathi':continue
        pid=p['sourceProductId']; source=products.get(pid)
        if not source or source['name']!=p['sourceName']:
            report['held'].append({'source':'ekalathi','productId':pid,'reason':'Missing or changed product name/pack'});continue
        response=fetch.get('https://www.e-kalathi.gov.cy/ekalathi-website-server/api/retail/fetch-retail-branch-list?productId='+pid+'&page=0&size=200&sort=DEFAULT,ASC')
        rows=response['content']
        if response.get('totalPages',1)>1 or len(rows)!=response['totalElements'] or len(rows)>200:raise ValueError('Incomplete branches')
        if len({r['id'] for r in rows})!=len(rows):raise ValueError('Duplicate branch')
        previous=dict(p['prices']);prices=[];bad=False
        for row in rows:
            sid='ekalathi:'+str(row['id']); shop=shops.get(sid)
            if not shop:
                report['newBranches'].add(sid);continue
            if retailer(row.get('companyName'))!=shop['retailer'] or clean(row['name'])!=clean(shop['name']) or clean(row.get('postalAddress'))!=clean(shop.get('address')):
                bad=True;report['held'].append({'source':'ekalathi','productId':pid,'shopId':sid,'reason':'Branch identity/address changed'});continue
            price=row.get('retailerProductPrice')
            if price is None or price==0:continue
            try:prices.append([sid,checked_price(price,previous.get(sid))])
            except ValueError as e:bad=True;report['held'].append({'source':'ekalathi','productId':pid,'shopId':sid,'reason':str(e)})
        # Atomic per product: avoid giving retained/held prices a fresh observation date.
        if bad or not prices or len(prices)<max(1,len(previous)*.8):
            report['held'].append({'source':'ekalathi','productId':pid,'reason':'Product held: changed branch, price anomaly or >20% coverage loss'});continue
        p['prices']=sorted(prices);p['observedAt']=stamp();report['updated']+=1
        if report['updated']%25==0: print('e-Kalathi products refreshed:',report['updated'],flush=True)

def alpha_record(p,row):
    if str(row.get('uniqueId'))!=p['sourceProductId'] or row.get('title')!=p['sourceName'] or barcode(row.get('barcode'))!=p.get('barcode'):raise ValueError('Product name, barcode or pack changed')
    if row.get('currency')!='EUR' or row.get('productUrl')!=p['sourceUrl']:raise ValueError('Currency/source changed')
    value=checked_price(row.get('price'),p['prices'][0][1])
    availability=str(row.get('availability')).lower()
    if availability not in ('true','false'):raise ValueError('Unknown availability response')
    p['prices']=[[p['prices'][0][0],value]];p['inStock']=availability=='true';p['observedAt']=stamp()

def refresh_alpha(fetch, book, report):
    config=fetch.get(ALPHA_CONFIG,as_json=False)
    client=[]
    for name in ('GetUnbxdApiKeyNT','GetUnbxdSiteNameNT'):
        fn=re.search(r'function '+name+r'\(\)\s*\{(.*?)\}',config,re.S)
        match=fn and re.search(r'return\s+[\x27"]([^\x27"]+)',fn[1])
        if not match:raise ValueError('Public search configuration changed')
        client.append(urllib.parse.quote(match[1],safe=''))
    products=[p for p in book['products'] if p['source']=='alphamega']
    for start in range(0,len(products),40):
        batch=products[start:start+40]
        # Original source barcodes may be shorter than the canonical GTIN14.
        codes=set()
        for p in batch:
            for n in (8,12,13,14):
                code=p['barcode'][-n:]
                if barcode(code)==p['barcode']:codes.add(code)
        params={'q':'*','filter':'barcode:('+' OR '.join('"'+c+'"' for c in sorted(codes))+')','rows':'100','fields':'uniqueId,barcode,title,brand,price,currency,availability,productUrl'}
        data=fetch.get('https://search.unbxd.io/'+'/'.join(client)+'/search?'+urllib.parse.urlencode(params),delay=10)['response']
        rows=data['products']
        if len(rows)!=data['numberOfProducts']:raise ValueError('Incomplete product response')
        by_id={str(r['uniqueId']):r for r in rows}
        if len(by_id)!=len(rows) or len({barcode(r['barcode']) for r in rows})!=len(rows):raise ValueError('Ambiguous barcode response')
        for p in batch:
            row=by_id.get(p['sourceProductId'])
            if not row:report['held'].append({'source':'alphamega','productId':p['sourceProductId'],'reason':'Not returned'});continue
            try:alpha_record(p,row);report['updated']+=1
            except ValueError as e:report['held'].append({'source':'alphamega','productId':p['sourceProductId'],'reason':str(e)})

def refresh_metro(fetch, book, report):
    page=fetch.get(METRO,as_json=False)
    match=re.search(r'window\.METRO_OFFERS\s*=\s*(\[.*?\]);',page,re.S)
    if not match:raise ValueError('Offer format changed')
    rows=json.loads(match[1]);by_id={}
    for row in rows:
        found=re.search(r'/leaflet/(\d+)\.',row.get('p',''))
        if found:
            if found[1] in by_id:raise ValueError('Duplicate offer ID')
            by_id[found[1]]=row
    for p in book['products']:
        if p['source']!='metro':continue
        row=by_id.get(p['sourceProductId'])
        if not row or row.get('t','').strip()!=p['sourceName'] or row.get('x'):
            report['held'].append({'source':'metro','productId':p['sourceProductId'],'reason':'Offer absent or identity/unit changed'});continue
        try:
            expiry=dt.date.fromisoformat(row['ed'])
            if not dt.date.today()<=expiry<=dt.date.today()+dt.timedelta(days=60):raise ValueError('Offer expired or date unexpected')
            if not re.fullmatch(r'\d+\.\d{2}',row['n']):raise ValueError('Invalid price')
            price=checked_price(float(row['n']),p['prices'][0][1])
            # Conservative UTC+03 expiry works across Cyprus daylight-saving changes.
            p['validUntil']=expiry.isoformat()+'T23:59:59+03:00'
            p['prices']=[[p['prices'][0][0],price]];p['observedAt']=stamp();report['updated']+=1
        except (ValueError,TypeError) as e:report['held'].append({'source':'metro','productId':p['sourceProductId'],'reason':str(e)})

def run():
    seed=json.loads((ROOT/'seed.json').read_text(encoding='utf-8'))
    path=ROOT/'prices.json';book=json.loads(path.read_text(encoding='utf-8')) if path.exists() else copy.deepcopy(seed)
    validate(book,seed);book['version']=VERSION
    report={'startedAt':stamp(),'sources':{},'newBranches':set(),'held':[]}
    fetch=Fetcher()
    for source,handler in [('ekalathi',refresh_kalathi),('alphamega',refresh_alpha),('metro',refresh_metro)]:
        candidate=copy.deepcopy(book);part={'updated':0,'held':[],'newBranches':set()}
        try:
            handler(fetch,candidate,part);validate(candidate,seed)
            book=candidate
            status='ok' if not part['held'] else 'partial'
            error=None
        except Exception as e:
            # Fail this source atomically; preserve every prior observation date.
            part['updated']=0;status='failed';error=type(e).__name__
        report['sources'][source]={'status':status,'updatedProducts':part['updated'],'heldProducts':len({x['productId'] for x in part['held']}),'error':error}
        report['held']+=part['held'];report['newBranches']|=part['newBranches']
        print(source,report['sources'][source],flush=True)
    report['finishedAt']=stamp();report['newBranches']=sorted(report['newBranches']);report['requests']=fetch.count
    book['generatedAt']=report['finishedAt'];book['sourceStatus']=report['sources']
    validate(book,seed)
    data=json.dumps(book,ensure_ascii=False,separators=(',',':'))
    if len(data.encode())>3_000_000:raise ValueError('Feed size bound exceeded')
    report['sha256']=hashlib.sha256(data.encode()).hexdigest()
    temp=path.with_suffix('.tmp');temp.write_text(data,encoding='utf-8');os.replace(temp,path)
    (ROOT/'status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['sources']['ekalathi']['updatedProducts']>0 and all(s['status']!='failed' for s in report['sources'].values()) else 2

if __name__=='__main__':raise SystemExit(run())

