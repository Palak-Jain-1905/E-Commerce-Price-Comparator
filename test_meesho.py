import requests
import json

key = '30040d9479b6720981bba90a5f7fa256'
url = 'https://www.myntra.com/goggles'
scraper_url = f'http://api.scraperapi.com?api_key={key}&url={url}'

print("Fetching...")
resp = requests.get(scraper_url, timeout=25)
raw = resp.text

idx = raw.find('window.__myx = {')
start = idx + len('window.__myx = ')
depth = 0
end = start
for i in range(start, len(raw)):
    ch = raw[i]
    if ch == '{': depth += 1
    elif ch == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break

data = json.loads(raw[start:end])
products = data['searchData']['results']['products']
print('Total products:', len(products))

# Pehle product ke saare keys dekho
p = products[0]
print("\nAll keys:", list(p.keys()))
print("\nFull first product:")
for k, v in p.items():
    print(f"  {k}: {v}")
    