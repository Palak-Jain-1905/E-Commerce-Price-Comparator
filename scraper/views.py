"""
Universal auto-detect scraper for PriceMatchX
Supports: Amazon, Flipkart, Meesho, Myntra
"""
from django.contrib.auth.decorators import login_required
from pathlib import Path
import mimetypes
import time
import random
import logging
from difflib import SequenceMatcher
from decimal import Decimal
import requests
from bs4 import BeautifulSoup

from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, JsonResponse
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Count
from django.utils.timezone import now, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchElementException, StaleElementReferenceException
)

from .models import Product, Offer, PriceHistory, SearchLog, LoginActivity, ResultCount, Wishlist

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_ITEMS         = 12
PAGE_LOAD_TIMEOUT = 25
SHORT_WAIT        = (1.2, 2.8)
FUZZY_THRESHOLD   = 0.52
TEMPLATES_DIR     = Path(__file__).resolve().parent / "templates"

FAKE_TITLES = [
    'add to compare', 'filters', 'need help?', 'sort by',
    'home', 'search', 'cart', 'wishlist', 'account',
    'login', 'signup', 'register', 'menu', 'close',
    'apply', 'clear', 'cancel', 'ok', 'done'
]

AMAZON_HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.co.in/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
]


# ------------------- Utilities -------------------

def template_video(request, filename: str):
    safe_name  = Path(filename).name
    candidates = [TEMPLATES_DIR / safe_name, TEMPLATES_DIR / "videos" / safe_name]
    for p in candidates:
        if p.exists():
            mime, _ = mimetypes.guess_type(str(p))
            return FileResponse(open(p, "rb"), content_type=mime or "video/mp4")
    raise Http404("Not found")


def rand_sleep(a=SHORT_WAIT[0], b=SHORT_WAIT[1]):
    time.sleep(random.uniform(a, b))


def is_fake_title(title):
    if not title or len(title) < 5:
        return True
    return title.lower().strip() in FAKE_TITLES


def get_driver(headless=False, disable_images=False):
    import os
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--lang=en-IN")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    if disable_images:
        prefs = {"profile.managed_default_content_settings.images": 2}
        chrome_options.add_experimental_option("prefs", prefs)

    try:
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            import subprocess
            try:
                chromium_path = subprocess.check_output(['which', 'chromium']).decode().strip()
            except:
                try:
                    chromium_path = subprocess.check_output(['which', 'chromium-browser']).decode().strip()
                except:
                    chromium_path = '/usr/bin/chromium'
            
            try:
                chromedriver_path = subprocess.check_output(['which', 'chromedriver']).decode().strip()
            except:
                chromedriver_path = '/usr/bin/chromedriver'
            
            chrome_options.binary_location = chromium_path
            service = Service(chromedriver_path)
        else:
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return driver
    except WebDriverException as e:
        logger.exception("ChromeDriver error: %s", e)
        raise


def safe_text(el):
    try:
        if el is None:
            return ""
        txt = el.text if hasattr(el, "text") else str(el)
        return txt.strip()
    except StaleElementReferenceException:
        return ""
    except Exception:
        return ""


def safe_int(text):
    if text is None:
        return None
    try:
        s = str(text).replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
        for token in s.split():
            num = "".join(ch for ch in token if (ch.isdigit() or ch == '.'))
            if num and any(ch.isdigit() for ch in num):
                if '.' in num:
                    return int(float(num))
                return int(num)
        return None
    except Exception:
        return None


def safe_decimal(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    try:
        s = str(v).replace(",", "")
        return Decimal(s)
    except Exception:
        return None


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ------------------- Site scrapers -------------------

def get_amazon_prices(driver, query):
    url = f"https://www.amazon.in/s?k={query}&ref=nb_sb_noss"
    print(f"\n[DEBUG] Amazon (requests): Loading {url}")
    prices, reviews, discounts, links, images, ratings = {}, {}, {}, {}, {}, {}

    try:
        headers = random.choice(AMAZON_HEADERS_LIST)
        session = requests.Session()
        session.headers.update(headers)
        time.sleep(random.uniform(1, 2))
        resp = session.get(url, timeout=15)
        print(f"[DEBUG] Amazon: Status = {resp.status_code}")

        if resp.status_code != 200:
            return prices, reviews, discounts, links

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("div[data-component-type='s-search-result']")
        print(f"[DEBUG] Amazon: Found {len(items)} items in HTML")

        products = []
        for item in items:
            try:
                title_el = item.select_one("h2 span") or item.select_one("span.a-text-normal")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 3 or is_fake_title(title):
                    continue
                if len(title) > 100:
                    title = title[:100] + "..."

                # Price
                price = None
                price_el = item.select_one("span.a-price-whole")
                if price_el:
                    price = safe_int(price_el.get_text(strip=True))
                if not price:
                    price_el = item.select_one("span.a-offscreen")
                    if price_el:
                        price = safe_int(price_el.get_text(strip=True))

                # Link
                link = "#"
                a_el = item.select_one("a.a-link-normal")
                if a_el and a_el.get("href"):
                    href = a_el["href"]
                    link = f"https://www.amazon.in{href}" if href.startswith("/") else href

                # Image
                image = ""
                img_el = item.select_one("img.s-image")
                if img_el:
                    image = img_el.get("src", "")

                # Rating (numeric)
                rating_val = 0.0
                rating_el = item.select_one("span.a-icon-alt")
                rating_text = "No reviews"
                if rating_el:
                    rating_text = rating_el.get_text(strip=True).split()[0]
                    try:
                        rating_val = float(rating_text)
                    except:
                        rating_val = 0.0

                # Review count
                review_count = 0
                review_el = item.select_one("span.a-size-base.s-underline-text")
                if review_el:
                    try:
                        review_count = int(review_el.get_text(strip=True).replace(",", ""))
                    except:
                        review_count = 0

                # Discount
                discount_text = "No discount"
                for span in item.select("span"):
                    t = span.get_text(strip=True).lower()
                    if "%" in t and "off" in t:
                        discount_text = span.get_text(strip=True)
                        break

                products.append({
                    "title": title,
                    "price": price,
                    "link": link,
                    "image": image,
                    "rating_text": rating_text,
                    "rating_val": rating_val,
                    "review_count": review_count,
                    "discount": discount_text,
                })

            except Exception:
                continue

        # Sort by rating first, then review count
        products.sort(key=lambda x: (x["rating_val"], x["review_count"]), reverse=True)

        # Take top MAX_ITEMS
        for prod in products[:MAX_ITEMS]:
            t = prod["title"]
            prices[t]    = prod["price"]
            reviews[t]   = prod["rating_text"]
            discounts[t] = prod["discount"]
            links[t]     = prod["link"]
            images[t]    = prod["image"]
            ratings[t]   = prod["rating_val"]

    except Exception as e:
        print(f"[DEBUG] Amazon requests failed: {e}")

    print(f"[DEBUG] Amazon: Scraped {len(prices)} items")
    return prices, reviews, discounts, links, images, ratings


SCRAPER_API_KEY = "30040d9479b6720981bba90a5f7fa256"

def get_flipkart_prices(driver, query):
    url = f"https://www.flipkart.com/search?q={query}"
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}"
    print(f"\n[DEBUG] Flipkart (ScraperAPI): Loading")
    prices, reviews, discounts, links = {}, {}, {}, {}
    try:
        resp = requests.get(scraper_url, timeout=60)
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div._75nlfW, div.tUxRFH, div.cPHDOP")
        print(f"[DEBUG] Flipkart: Found {len(cards)} cards")
        for card in cards[:MAX_ITEMS]:
            try:
                title_el = card.select_one("div.KzDlHZ, a.WKTcLC, div._4rR01T, a.s1Q9rs")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or is_fake_title(title):
                    continue
                price_el = card.select_one("div.Nx9bqj, div._30jeq3")
                price = safe_int(price_el.get_text(strip=True)) if price_el else None
                link_el = card.select_one("a")
                href = link_el.get("href", "#") if link_el else "#"
                link = f"https://www.flipkart.com{href}" if href.startswith("/") else href
                disc_el = card.select_one("div.UkUFwK, div._3Ay6Sb")
                discount = disc_el.get_text(strip=True) if disc_el else "No discount"
                prices[title] = price
                links[title] = link
                discounts[title] = discount
                reviews[title] = "No reviews"
            except Exception:
                continue
    except Exception as e:
        print(f"[DEBUG] Flipkart ScraperAPI failed: {e}")
    print(f"[DEBUG] Flipkart: Scraped {len(prices)} items")
    return prices, reviews, discounts, links


def get_meesho_prices(driver, query):
    url = f"https://www.meesho.com/search?q={query}"
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}&render=true"
    print(f"\n[DEBUG] Meesho (ScraperAPI): Loading")
    prices, reviews, discounts, links = {}, {}, {}, {}
    try:
        resp = requests.get(scraper_url, timeout=60)
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.sc-bqiRlB, div.NewProductCardstyled__CardStyled-sc-6y2tys-0")
        print(f"[DEBUG] Meesho: Found {len(cards)} cards")
        for card in cards[:MAX_ITEMS]:
            try:
                title_el = card.select_one("p, h3")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or is_fake_title(title):
                    continue
                price_el = card.select_one("h5, span.price")
                price = safe_int(price_el.get_text(strip=True)) if price_el else None
                link_el = card.select_one("a")
                href = link_el.get("href", "#") if link_el else "#"
                link = f"https://www.meesho.com{href}" if href.startswith("/") else href
                prices[title] = price
                links[title] = link
                discounts[title] = "No discount"
                reviews[title] = "No reviews"
            except Exception:
                continue
    except Exception as e:
        print(f"[DEBUG] Meesho ScraperAPI failed: {e}")
    print(f"[DEBUG] Meesho: Scraped {len(prices)} items")
    return prices, reviews, discounts, links


def get_myntra_prices(driver, query):
    url = f"https://www.myntra.com/{query}"
    scraper_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}&render=true"
    print(f"\n[DEBUG] Myntra (ScraperAPI): Loading")
    prices, reviews, discounts, links = {}, {}, {}, {}
    try:
        resp = requests.get(scraper_url, timeout=60)
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("li.product-base")
        print(f"[DEBUG] Myntra: Found {len(cards)} cards")
        for card in cards[:MAX_ITEMS]:
            try:
                brand = card.select_one(".product-brand")
                name = card.select_one(".product-product")
                title = f"{brand.get_text(strip=True) if brand else ''} {name.get_text(strip=True) if name else ''}".strip()
                if not title or is_fake_title(title):
                    continue
                price_el = card.select_one(".product-discountedPrice, .product-price")
                price = safe_int(price_el.get_text(strip=True)) if price_el else None
                link_el = card.select_one("a")
                href = link_el.get("href", "#") if link_el else "#"
                link = f"https://www.myntra.com/{href}" if not href.startswith("http") else href
                disc_el = card.select_one(".product-discountPercentage")
                discount = disc_el.get_text(strip=True) if disc_el else "No discount"
                prices[title] = price
                links[title] = link
                discounts[title] = discount
                reviews[title] = "No reviews"
            except Exception:
                continue
    except Exception as e:
        print(f"[DEBUG] Myntra ScraperAPI failed: {e}")
    print(f"[DEBUG] Myntra: Scraped {len(prices)} items")
    return prices, reviews, discounts, links


# ------------------- Align / merge results -------------------

def align_results(amazon_prices, flipkart_prices, meesho_prices, myntra_prices,
                  amazon_reviews=None, flipkart_reviews=None, meesho_reviews=None, myntra_reviews=None,
                  amazon_discounts=None, flipkart_discounts=None, meesho_discounts=None, myntra_discounts=None,
                  amazon_links=None, flipkart_links=None, meesho_links=None, myntra_links=None):

    A_keys  = list(amazon_prices.keys())
    F_keys  = list(flipkart_prices.keys())
    M_keys  = list(meesho_prices.keys())
    Y_keys  = list(myntra_prices.keys())
    lists   = [A_keys, F_keys, M_keys, Y_keys]
    max_len = max((len(l) for l in lists), default=0)
    rows    = []

    if A_keys:
        for i, at in enumerate(A_keys):
            row = {
                "product":           at,
                "amazon_price":      amazon_prices.get(at),
                "flipkart_price":    None,
                "meesho_price":      None,
                "myntra_price":      None,
                "amazon_reviews":    (amazon_reviews or {}).get(at),
                "flipkart_reviews":  None,
                "meesho_reviews":    None,
                "myntra_reviews":    None,
                "amazon_discount":   (amazon_discounts or {}).get(at),
                "flipkart_discount": None,
                "meesho_discount":   None,
                "myntra_discount":   None,
                "amazon_link":       (amazon_links or {}).get(at),
                "flipkart_link":     None,
                "meesho_link":       None,
                "myntra_link":       None,
                "cheaper_on":        None,
            }

            best_f, best_f_score = None, 0.0
            for fk in F_keys:
                s = similar(at, fk)
                if s > best_f_score:
                    best_f_score = s; best_f = fk
            if best_f_score >= FUZZY_THRESHOLD and best_f:
                row["flipkart_price"]    = flipkart_prices.get(best_f)
                row["flipkart_reviews"]  = (flipkart_reviews or {}).get(best_f)
                row["flipkart_discount"] = (flipkart_discounts or {}).get(best_f)
                row["flipkart_link"]     = (flipkart_links or {}).get(best_f)

            best_m, best_m_score = None, 0.0
            for mk in M_keys:
                s = similar(at, mk)
                if s > best_m_score:
                    best_m_score = s; best_m = mk
            if best_m_score >= FUZZY_THRESHOLD and best_m:
                row["meesho_price"]    = meesho_prices.get(best_m)
                row["meesho_reviews"]  = (meesho_reviews or {}).get(best_m)
                row["meesho_discount"] = (meesho_discounts or {}).get(best_m)
                row["meesho_link"]     = (meesho_links or {}).get(best_m)

            best_y, best_y_score = None, 0.0
            for yk in Y_keys:
                s = similar(at, yk)
                if s > best_y_score:
                    best_y_score = s; best_y = yk
            if best_y_score >= FUZZY_THRESHOLD and best_y:
                row["myntra_price"]    = myntra_prices.get(best_y)
                row["myntra_reviews"]  = (myntra_reviews or {}).get(best_y)
                row["myntra_discount"] = (myntra_discounts or {}).get(best_y)
                row["myntra_link"]     = (myntra_links or {}).get(best_y)

            if all(row.get(k) is None for k in ("flipkart_price", "meesho_price", "myntra_price")):
                j = i
                if j < len(F_keys):
                    fk = F_keys[j]
                    row["flipkart_price"]    = flipkart_prices.get(fk)
                    row["flipkart_reviews"]  = (flipkart_reviews or {}).get(fk)
                    row["flipkart_discount"] = (flipkart_discounts or {}).get(fk)
                    row["flipkart_link"]     = (flipkart_links or {}).get(fk)
                if j < len(M_keys):
                    mk = M_keys[j]
                    row["meesho_price"]    = meesho_prices.get(mk)
                    row["meesho_reviews"]  = (meesho_reviews or {}).get(mk)
                    row["meesho_discount"] = (meesho_discounts or {}).get(mk)
                    row["meesho_link"]     = (meesho_links or {}).get(mk)
                if j < len(Y_keys):
                    yk = Y_keys[j]
                    row["myntra_price"]    = myntra_prices.get(yk)
                    row["myntra_reviews"]  = (myntra_reviews or {}).get(yk)
                    row["myntra_discount"] = (myntra_discounts or {}).get(yk)
                    row["myntra_link"]     = (myntra_links or {}).get(yk)

            price_map = {
                "Amazon":   row.get("amazon_price"),
                "Flipkart": row.get("flipkart_price"),
                "Meesho":   row.get("meesho_price"),
                "Myntra":   row.get("myntra_price"),
            }
            min_store, min_val = None, float("inf")
            for store, v in price_map.items():
                try:
                    if v is None: continue
                    fv = float(v)
                    if fv < min_val:
                        min_val = fv; min_store = store
                except Exception:
                    continue
            row["cheaper_on"] = min_store
            rows.append(row)
        return rows

    for i in range(max_len):
        title = None
        if i < len(A_keys):   title = A_keys[i]
        elif i < len(F_keys): title = F_keys[i]
        elif i < len(M_keys): title = M_keys[i]
        elif i < len(Y_keys): title = Y_keys[i]

        row = {
            "product":        title,
            "amazon_price":   amazon_prices.get(title)       if title in amazon_prices  else None,
            "flipkart_price": flipkart_prices.get(F_keys[i]) if i < len(F_keys)        else None,
            "meesho_price":   meesho_prices.get(M_keys[i])   if i < len(M_keys)        else None,
            "myntra_price":   myntra_prices.get(Y_keys[i])   if i < len(Y_keys)        else None,
        }
        min_store, min_val = None, float("inf")
        for store, v in (
            ("Amazon",   row["amazon_price"]),
            ("Flipkart", row["flipkart_price"]),
            ("Meesho",   row["meesho_price"]),
            ("Myntra",   row["myntra_price"]),
        ):
            try:
                if v is None: continue
                fv = float(v)
                if fv < min_val:
                    min_val = fv; min_store = store
            except Exception:
                continue
        row["cheaper_on"] = min_store
        rows.append(row)
    return rows


# ------------------- DB upsert helper -------------------

def upsert_product_offer_from_row(row: dict) -> Product:
    title = row.get("product") or "Unnamed product"
    p, _  = Product.objects.get_or_create(title=title)
    try:
        p.save()
    except Exception:
        logger.exception("Error saving Product")

    def save_offer(store_key, store_name):
        price = row.get(f"{store_key}_price")
        link  = row.get(f"{store_key}_link") or "#"
        if price is None:
            return None
        price_d = safe_decimal(price)
        try:
            o, _ = Offer.objects.update_or_create(
                product=p, store=store_name,
                defaults={
                    "url":        link,
                    "price":      price_d,
                    "discount":   (row.get(f"{store_key}_discount") or "")[:200],
                    "review_cnt": None,
                }
            )
            if price_d is not None:
                PriceHistory.objects.create(offer=o, price=price_d)
            return o
        except Exception:
            logger.exception("Failed to save offer %s", store_name)
            return None

    save_offer("amazon",   "amazon")
    save_offer("flipkart", "flipkart")
    save_offer("meesho",   "meesho")
    save_offer("myntra",   "myntra")
    return p


# ------------------- Main compare view -------------------

@login_required
def compare_prices(request):
    query = (request.GET.get("q") or request.GET.get("query") or "").strip()

    if not query:
        return render(request, "index.htm", {"error": "Please enter a product name", "query": ""})

    if not request.session.session_key:
        request.session.save()

    try:
        SearchLog.objects.create(
            query=query,
            user=request.user if request.user.is_authenticated else None,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except Exception as e:
        logger.exception("SearchLog save failed: %s", e)

    print(f"\n{'='*60}\n[DEBUG] Search: '{query}'\n{'='*60}")

    import os
    try:
        driver = get_driver(headless=False, disable_images=False)
    except Exception as e:
        logger.exception("Driver init failed: %s", e)
        driver = None

    try:
    # Amazon uses requests (Railway pe bhi chalega)
        amazon_prices, amazon_reviews, amazon_discounts, amazon_links, amazon_images, amazon_ratings = get_amazon_prices(None, query)

        # Flipkart, Meesho, Myntra sirf local pe (Selenium chahiye)
        if driver:
            rand_sleep()
            flipkart_prices, flipkart_reviews, flipkart_discounts, flipkart_links = get_flipkart_prices(driver, query)
            rand_sleep()
            meesho_prices,   meesho_reviews,   meesho_discounts,   meesho_links   = get_meesho_prices(driver, query)
            rand_sleep()
            myntra_prices,   myntra_reviews,   myntra_discounts,   myntra_links   = get_myntra_prices(driver, query)
        else:
            flipkart_prices, flipkart_reviews, flipkart_discounts, flipkart_links = {}, {}, {}, {}
            meesho_prices,   meesho_reviews,   meesho_discounts,   meesho_links   = {}, {}, {}, {}
            myntra_prices,   myntra_reviews,   myntra_discounts,   myntra_links   = {}, {}, {}, {}
    except Exception as e:
        logger.exception("Scraping error: %s", e)
        return render(request, "index.htm", {"error": "Scrape failed. Check server logs."})
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

    print(f"\n[DEBUG] TOTAL — Amazon:{len(amazon_prices)} Flipkart:{len(flipkart_prices)} Meesho:{len(meesho_prices)} Myntra:{len(myntra_prices)}")

    comparisons = align_results(
        amazon_prices,   flipkart_prices,   meesho_prices,   myntra_prices,
        amazon_reviews=amazon_reviews,      flipkart_reviews=flipkart_reviews,
        meesho_reviews=meesho_reviews,      myntra_reviews=myntra_reviews,
        amazon_discounts=amazon_discounts,  flipkart_discounts=flipkart_discounts,
        meesho_discounts=meesho_discounts,  myntra_discounts=myntra_discounts,
        amazon_links=amazon_links,          flipkart_links=flipkart_links,
        meesho_links=meesho_links,          myntra_links=myntra_links,
    )

    for row in comparisons:
        prod = row.get("product")
        row.setdefault("amazon_link",       amazon_links.get(prod))
        row.setdefault("amazon_discount",   amazon_discounts.get(prod, "No discount"))
        row.setdefault("amazon_reviews",    amazon_reviews.get(prod, "No reviews"))
        row.setdefault("flipkart_link",     flipkart_links.get(prod))
        row.setdefault("flipkart_discount", flipkart_discounts.get(prod, "No discount"))
        row.setdefault("flipkart_reviews",  flipkart_reviews.get(prod, "No reviews"))
        row.setdefault("meesho_link",       meesho_links.get(prod))
        row.setdefault("meesho_discount",   meesho_discounts.get(prod, "No discount"))
        row.setdefault("meesho_reviews",    meesho_reviews.get(prod, "No reviews"))
        row.setdefault("myntra_link",       myntra_links.get(prod))
        row.setdefault("myntra_discount",   myntra_discounts.get(prod, "No discount"))
        row.setdefault("myntra_reviews",    myntra_reviews.get(prod, "No reviews"))
        row.setdefault("amazon_image",  amazon_images.get(prod, ""))
        row.setdefault("amazon_rating", amazon_ratings.get(prod, 0))

    for row in comparisons:
        try:
            if not row.get("product"):
                continue
            p = upsert_product_offer_from_row(row)
            row["slug"] = getattr(p, "slug", None)
        except Exception:
            logger.exception("Upsert failed for: %s", row.get("product"))

    try:
        search_log = SearchLog.objects.filter(query=query).last()
        if search_log:
            ResultCount.objects.update_or_create(
                search_log=search_log,
                defaults=dict(
                    amazon=len(amazon_prices),
                    flipkart=len(flipkart_prices),
                    meesho=len(meesho_prices),
                    myntra=len(myntra_prices),
                )
            )
    except Exception as e:
        logger.exception("ResultCount save failed: %s", e)

    print(f"[DEBUG] Final rows: {len(comparisons)}")
    return render(request, "result.htm", {"comparisons": comparisons, "query": query})


# ------------------- Auth views -------------------

def welcome(request):
    return render(request, "welcome.htm")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("welcome")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            try:
                LoginActivity.objects.create(
                    user=user,
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    success=True,
                )
            except Exception:
                logger.exception("LoginActivity save failed on signup")
            nxt = request.POST.get("next") or request.GET.get("next")
            if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
                return redirect(nxt)
            return redirect("welcome")
    else:
        form = UserCreationForm()
    return render(request, "auth/signup.html", {"form": form, "next": request.GET.get("next", "")})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("welcome")
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            try:
                LoginActivity.objects.create(
                    user=user,
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    success=True,
                )
            except Exception:
                logger.exception("LoginActivity save failed on login")
            nxt = request.POST.get("next") or request.GET.get("next")
            if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
                return redirect(nxt)
            return redirect("welcome")
    else:
        form = AuthenticationForm(request)
    return render(request, "auth/login.html", {"form": form, "next": request.GET.get("next", "")})


def logout_view(request):
    logout(request)
    return redirect("login")


def product_detail(request, slug):
    p      = get_object_or_404(Product, slug=slug)
    offers = Offer.objects.filter(product=p).order_by("price")
    labels, values = [], []
    if offers:
        cheapest = offers[0]
        qs = PriceHistory.objects.filter(offer=cheapest).order_by("ts").only("ts", "price")[:180]
        labels = [h.ts.strftime("%d %b") for h in qs]
        values = [float(h.price) for h in qs]
    best_offer = offers.first()
    return render(request, "product_detail.html", {
        "product":    p,
        "offers":     offers,
        "best_offer": best_offer,
        "labels":     labels,
        "values":     values,
    })


def api_suggest(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"q": q, "items": []})
    prod_titles = list(Product.objects.filter(title__icontains=q).values_list("title", flat=True)[:10])
    items       = [{"text": t, "type": "product"} for t in prod_titles]
    since       = now() - timedelta(days=60)
    logs = SearchLog.objects.filter(ts__gte=since, query__icontains=q).values("query").annotate(n=Count("id")).order_by("-n")[:10]
    seen = {t.lower() for t in prod_titles}
    for r in logs:
        t = r["query"]
        if t.lower() not in seen:
            items.append({"text": t, "type": "query"})
            seen.add(t.lower())
    return JsonResponse({"q": q, "items": items[:8]})


def add_watch(request, slug):
    if not request.user.is_authenticated:
        return redirect("login")
    product = get_object_or_404(Product, slug=slug)
    if request.method == "POST":
        target = request.POST.get("target_price") or None
        email  = request.POST.get("email") or None
        try:
            Wishlist.objects.update_or_create(
                user=request.user, product=product,
                defaults={
                    "alert_on_drop": True,
                    "target_price":  target,
                    "email_alert":   email,
                }
            )
        except Exception:
            logger.exception("Wishlist save failed")
    return redirect("product_detail", slug=slug)


def remove_watch(request, slug):
    if not request.user.is_authenticated:
        return redirect('login')
    product = get_object_or_404(Product, slug=slug)
    if request.method == 'POST':
        Wishlist.objects.filter(user=request.user, product=product).delete()
    return redirect('profile')


def task_status(request, task_id):
    return JsonResponse({"status": "done", "task_id": task_id})


def loading_view(request):
    query = (request.GET.get("q") or request.GET.get("query") or "").strip()
    return render(request, "loading.html", {"query": query})


def profile_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    wishlist = Wishlist.objects.filter(
        user=request.user
    ).select_related('product').order_by('-added_at')
    history = SearchLog.objects.filter(
        user=request.user
    ).order_by('-ts')[:20]
    return render(request, 'profile.html', {
        'wishlist': wishlist,
        'history': history
    })

# ------------------- Cart & Order views -------------------

from .models import Cart, CartItem, Order, OrderItem

def cart_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('offer__product').all()
    return render(request, 'cart.html', {'cart': cart, 'items': items})


def add_to_cart(request, offer_id):
    if not request.user.is_authenticated:
        return redirect('login')
    offer = get_object_or_404(Offer, id=offer_id)
    cart, _ = Cart.objects.get_or_create(user=request.user)
    item, created = CartItem.objects.get_or_create(cart=cart, offer=offer)
    if not created:
        item.quantity += 1
        item.save()
    return redirect('cart')


def remove_from_cart(request, item_id):
    if not request.user.is_authenticated:
        return redirect('login')
    item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    if request.method == 'POST':
        item.delete()
    return redirect('cart')


def place_order(request):
    if not request.user.is_authenticated:
        return redirect('login')
    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = cart.items.select_related('offer__product').all()
    if not items:
        return redirect('cart')
    if request.method == 'POST':
        total = sum(item.subtotal() for item in items)
        order = Order.objects.create(
            user=request.user,
            total_price=total,
            status='confirmed'
        )
        for item in items:
            OrderItem.objects.create(
                order=order,
                product=item.offer.product,
                store=item.offer.store,
                store_url=item.offer.url,
                price=item.offer.price or 0,
                quantity=item.quantity,
            )
        cart.items.all().delete()
        return redirect('order_detail', pk=order.pk)
    return redirect('cart')


def order_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect('login')
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return render(request, 'order_detail.html', {'order': order})


def order_history(request):
    if not request.user.is_authenticated:
        return redirect('login')
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product')
    return render(request, 'order_history.html', {'orders': orders})



from django.core.mail import send_mail

def check_price_alerts():
    """Sab wishlist items check karo — agar price target se kam ho toh email bhejo"""
    alerts = Wishlist.objects.filter(
        alert_on_drop=True,
        target_price__isnull=False,
        email_alert__isnull=False
    ).select_related('product', 'user')
    
    for alert in alerts:
        try:
            cheapest_offer = Offer.objects.filter(
                product=alert.product,
                price__isnull=False
            ).order_by('price').first()
            
            if not cheapest_offer:
                continue
                
            if cheapest_offer.price <= alert.target_price:
                send_mail(
                    subject=f'🎉 Price Drop Alert! {alert.product.title[:40]}',
                    message=f'''
price alert!

Product: {alert.product.title}
Target Price: ₹{alert.target_price}
Current Price: ₹{cheapest_offer.price} on {cheapest_offer.store.capitalize()}
Link: {cheapest_offer.url}

PriceMatchX pe dekho: http://127.0.0.1:8000/p/{alert.product.slug}/
                    ''',
                    from_email='palakjain87654@gmail.com',
                    recipient_list=[alert.email_alert],
                    fail_silently=True,
                )
                print(f"[ALERT] Email sent to {alert.email_alert} for {alert.product.title}")
        except Exception as e:
            print(f"[ALERT ERROR] {e}")
def run_price_alerts(request):
    check_price_alerts()
    return JsonResponse({"status": "done", "message": "Alerts checked!"})