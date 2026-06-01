import feedparser
import requests
from bs4 import BeautifulSoup
import re
import json
import time
from datetime import datetime

CATEGORY_FEEDS = {
    "home": {
        "label": "🏠 홈 가구",
        "day": 0,  # 월요일 — 주거 공간에 놓이는 가구·소품
        "keywords": ["sofa", "couch", "dining table", "coffee table", "sideboard", "wardrobe", "bookshelf", "bedside", "home furniture", "living room", "bedroom furniture", "rug", "cushion", "home decor", "residential furniture"],
        "feeds": {
            "Dezeen": "https://www.dezeen.com/feed/",
            "Design Milk": "https://design-milk.com/feed/",
            "Remodelista": "https://www.remodelista.com/feed/",
            "Curbed": "https://www.curbed.com/rss/index.xml",
            "Apartment Therapy": "https://www.apartmenttherapy.com/main.rss",
            "Est Living": "https://www.estliving.com/feed/",
            "Leibal": "https://leibal.com/feed/",
            "Yellowtrace": "https://www.yellowtrace.com.au/feed/",
            "The Nordroom": "https://www.thenordroom.com/feed/",
        }
    },
    "office": {
        "label": "🏢 오피스·상업공간 가구",
        "day": 1,  # 화요일 — 업무·상업 환경용 가구
        "keywords": ["office furniture", "office chair", "desk", "workstation", "task chair", "conference table", "lounge", "contract furniture", "workplace furniture", "commercial furniture", "reception", "hospitality furniture", "hotel furniture"],
        "exclude_keywords": ["lamp", "table lamp", "pendant", "floor lamp", "rug", "sofa", "couch", "sideboard", "dresser", "residential", "apartment", "bedroom", "living room", "home decor", "chair review"],
        "feeds": {
            "Office Snapshots": "https://officesnapshots.com/feed/",
            "Officelovin": "https://officelovin.com/feed/",
            "Contract Design": "https://www.contractdesign.com/feed/",
            "Work Design Mag": "https://www.workdesign.com/feed/",
            "Dezeen": "https://www.dezeen.com/feed/",
            "Hospitality Design": "https://hospitalitydesign.com/feed/",
            "Designboom": "https://www.designboom.com/architecture/feed/",
        }
    },
    "chair": {
        "label": "🪑 체어 (의자)",
        "day": 2,  # 수요일 — 의자 단품 디자인에 집중
        "keywords": ["chair", "armchair", "stool", "seating", "seat", "dining chair", "lounge chair", "side chair", "rocking chair", "chaise", "ottoman", "bench"],
        "exclude_keywords": ["table", "sofa", "couch", "lamp", "lighting", "shelf", "cabinet", "wardrobe", "bed", "rug", "curtain", "storage"],
        "feeds": {
            "Dezeen Design": "https://www.dezeen.com/design/feed/",
            "Designboom Design": "https://www.designboom.com/design/feed/",
            "Yanko Design Furniture": "https://www.yankodesign.com/category/furniture/feed/",
            "Core77": "https://www.core77.com/feed",
            "Wallpaper Design": "https://www.wallpaper.com/design/rss",
            "Frame Magazine": "https://www.frameweb.com/feed",
            "Cool Hunting": "https://coolhunting.com/feed/",
        }
    },
    "space": {
        "label": "🌐 공간·건축·트렌드",
        "day": 3,  # 목요일 — 가구 없는 건축·공간·소재 트렌드
        "keywords": ["architecture", "building", "facade", "pavilion", "installation", "exhibition", "biennale", "material", "structure", "museum", "gallery", "public space", "urban", "sustainability", "renovation"],
        "feeds": {
            "Dezeen Architecture": "https://www.dezeen.com/architecture/feed/",
            "ArchDaily": "https://www.archdaily.com/feed",
            "Designboom Architecture": "https://www.designboom.com/architecture/feed/",
            "Surface Magazine": "https://www.surfacemag.com/feed/",
            "Azure Magazine": "https://www.azuremagazine.com/feed/",
            "Curbed": "https://www.curbed.com/rss/index.xml",
            "Architectural Digest": "https://www.architecturaldigest.com/feed/rss",
        }
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}


def get_clean_summary(entry, article_url):
    html_content = entry.get("summary", "") or entry.get("description", "")

    if not html_content.strip() or len(html_content) < 30:
        try:
            res = requests.get(article_url, headers=HEADERS, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                meta_desc = soup.find("meta", name="description") or soup.find("meta", property="og:description")
                if meta_desc and meta_desc.get("content"):
                    html_content = meta_desc["content"]
                else:
                    paragraphs = soup.find_all("p")
                    html_content = " ".join([p.get_text() for p in paragraphs[:2]])
        except Exception:
            pass

    if not html_content:
        return "요약 정보가 제공되지 않는 기사입니다."

    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ").strip()
    text = re.sub(r'\s+', ' ', text)

    sentences = re.split(r'(?<=[.!?])\s+', text)
    clean_sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

    summary_3_lines = " ".join(clean_sentences[:3])
    return summary_3_lines if summary_3_lines else "본문 요약본 추출 실패"


def get_image_url(entry, article_url):
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "links" in entry:
        for link in entry.links:
            if "image" in link.get("type", ""):
                return link.get("href")

    try:
        response = requests.get(article_url, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]

            tw_image = soup.find("meta", name="twitter:image")
            if tw_image and tw_image.get("content"):
                return tw_image["content"]

            first_img = soup.find("img", src=True)
            if first_img and first_img["src"].startswith("http"):
                return first_img["src"]
    except Exception:
        pass

    return "https://via.placeholder.com/800x500.png?text=Furniture+Trend+Image"


def scrape_newsletter_trends(category_key: str) -> dict:
    category = CATEGORY_FEEDS[category_key]
    feeds = category["feeds"]
    label = category["label"]

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{label}] {len(feeds)}개 사이트 수집 시작...")
    all_articles = {}

    for site_name, feed_url in feeds.items():
        print(f"  {site_name} 수집 중... ", end="", flush=True)
        all_articles[site_name] = []

        try:
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print("실패 (서버 응답 없음)")
                continue

            count = 0
            for entry in feed.entries[:5]:
                title = entry.get("title", "제목 없음").strip()
                link = entry.get("link", "").strip()

                if not link:
                    continue

                summary = get_clean_summary(entry, link)
                image_url = get_image_url(entry, link)

                all_articles[site_name].append({
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "image_url": image_url
                })
                count += 1

            print(f"완료 ({count}개)")
            time.sleep(1)

        except Exception as e:
            print(f"에러 (건너뜀): {e}")
            continue

    output_file = f"trends_report_{category_key}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=4)

    print(f"\n수집 완료. '{output_file}' 저장됨.")
    return all_articles


if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else "furniture"
    if key not in CATEGORY_FEEDS:
        print(f"알 수 없는 카테고리: {key}. 가능한 값: {list(CATEGORY_FEEDS.keys())}")
        sys.exit(1)
    scrape_newsletter_trends(key)
