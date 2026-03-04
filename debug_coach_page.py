"""
DEBUG v2 - Check multiple sites for coach composition
Run: python debug_coach_page.py
"""
import requests
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
train_no = "10101"

urls = [
    f"https://www.trainspnrstatus.com/coach-composition/{train_no}",
    f"https://www.trainspnrstatus.com/trains/{train_no}",
    f"https://erail.in/train/{train_no}",
    f"https://etrain.info/in/trains/{train_no}",
    f"https://runningstatus.in/train/{train_no}",
]

for url in urls:
    print(f"\n{'='*60}")
    print(f"URL: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            print(f"Title: {title.get_text() if title else 'None'}")
            # Look for class-related keywords
            body = soup.get_text(' ', strip=True)
            # Find context around coach-related words
            import re
            for kw in ['sleeper','AC','coach','class','1A','2A','3A','SL','CC']:
                m = re.search(rf'.{{0,60}}{kw}.{{0,60}}', body, re.I)
                if m:
                    print(f"  [{kw}]: ...{m.group()}...")
                    break
            print(f"Body (first 600 chars): {body[:600]}")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone!")