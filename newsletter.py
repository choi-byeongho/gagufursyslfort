import json
import os
import re
import sys
import time
import requests
from groq import Groq
from json_repair import repair_json
from deep_translator import GoogleTranslator
from datetime import datetime
from dotenv import load_dotenv

from scraper import scrape_newsletter_trends, CATEGORY_FEEDS

load_dotenv()

CATEGORY_COLORS = {
    "home":   {"primary": "#2d6a4f", "light": "#d8f3dc"},
    "office": {"primary": "#1d4e89", "light": "#dbe9f9"},
    "chair":  {"primary": "#b5451b", "light": "#fde8e0"},
    "space":  {"primary": "#4a1d8a", "light": "#ede9fe"},
}

SENT_ARTICLES_FILE = "sent_articles.json"
SENT_EXPIRY_DAYS = 30


def load_sent_urls() -> set:
    """이미 전송된 기사 URL 목록을 로드. 30일 초과 항목은 자동 삭제."""
    if not os.path.exists(SENT_ARTICLES_FILE):
        return set()
    try:
        with open(SENT_ARTICLES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cutoff = datetime.now().timestamp() - SENT_EXPIRY_DAYS * 86400
        return {url for url, ts in data.items() if ts > cutoff}
    except Exception:
        return set()


def save_sent_urls(sent_urls: set, new_urls: list):
    """새로 전송한 URL을 sent_articles.json에 추가 저장."""
    try:
        existing = {}
        if os.path.exists(SENT_ARTICLES_FILE):
            with open(SENT_ARTICLES_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        now_ts = datetime.now().timestamp()
        for url in new_urls:
            existing[url] = now_ts
        # 30일 초과 항목 정리
        cutoff = now_ts - SENT_EXPIRY_DAYS * 86400
        existing = {url: ts for url, ts in existing.items() if ts > cutoff}
        with open(SENT_ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  경고: sent_articles.json 저장 실패: {e}")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

SUMMARY_STYLE_PROMPT = """당신은 한국의 프리미엄 인테리어·가구 매거진 《가구백서》의 수석 에디터입니다.
아래 영문 기사들을 읽고, 각각을 한국어 매거진 기사 문체로 2~3문장 요약하세요.

[필수 규칙]
1. 직역·번역투 절대 금지. "~하였습니다", "~합니다" 같은 경어체 금지. 문어체 평서문으로 작성.
2. 영문을 그대로 옮기지 말고, 한국 독자가 자연스럽게 읽히도록 재구성할 것.
3. 브랜드명·스튜디오명·인명은 영문 그대로 유지 (예: Kuma&Elsa, Selldorf Architects).
4. 출처 사이트명(Dezeen, Designboom 등)은 절대 본문에 넣지 말 것.
5. 문장은 항상 완결된 형태로 끝낼 것. 미완성 문장 금지.
6. 제목도 자연스러운 한국어로 의역 (브랜드명 제외).
7. [절대 규칙] 한국어, 영문, 숫자, 기본 문장부호 외 모든 문자 사용 금지. 한자(漢字)·히라가나·가타카나 포함 시 해당 응답 전체 무효 처리.
8. 문장을 짧고 끊어서 쓸 것. 호흡이 짧아야 읽기 좋다. 한 문장에 두 가지 내용을 넣지 말 것.
8. 독자에게 말 걸듯 가볍게, 하지만 전문적으로.
9. 마지막 문장은 이 디자인/공간이 왜 흥미로운지 한 줄 평으로 끝낼 것.
10. "~하였다", "~되었다" 같은 딱딱한 과거형 금지. 현재형으로 쓸 것.

[좋은 예시]
원문: "Kuma&Elsa arranges Japanese apartments around a translucent 'hut'"
나쁜 요약(번역투): "건축 스튜디오 Kuma&Elsa는 일본의 한 아파트 블록의 최상층 2개 층을 개조하여 전통적인 일본 엔가와의 공간적 조건을 재현하는 것을 목표로 하는 인클로저를 만들었습니다."
좋은 요약(매거진체): "도쿄의 한 아파트 옥상에서 Kuma&Elsa는 조용한 실험을 시도했다. 전통 일본 건축의 완충 공간인 엔가와를 현대 주거 안으로 끌어들인 것이다. 도시 속에서 오래된 감각을 되살리는 이 시도는, 생각보다 꽤 설득력 있게 읽힌다."

원문: "selldorf architects wins competition for Louvre renovation"
나쁜 요약(번역투): "selldorf architects와 STUDIOS architecture가 루브르 박물관의 새로운 변신을 위한 공모전에서 승리했다."
좋은 요약(매거진체): "루브르의 다음 챕터를 쓸 건축가로 Selldorf Architects가 낙점됐다. STUDIOS architecture와 협력해 제안한 이들의 계획은 미술관의 역사적 맥락을 존중하면서도 현대적 감각을 더하는 방향으로 주목을 받았다."

[기사 목록]
{articles_text}

반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 설명 없이 JSON만 출력하세요:
[
  {{"korean_title": "한국어 제목", "korean_summary": "2~3문장 매거진체 요약"}},
  ...
]"""


def _sanitize_korean(text: str) -> str:
    # CJK 한자/히라가나/가타카나 제거, 한글(U+AC00-U+D7A3)은 보존
    cleaned = re.sub(
        r'[぀-ヿ㐀-䶿一-鿿豈-﫿]', '', text
    )
    return re.sub(r'\s+', ' ', cleaned).strip()


def _extract_json(text: str):
    """응답 텍스트에서 JSON 배열을 안정적으로 추출."""
    # ```json ... ``` 블록 제거
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("["):
                text = part
                break

    # [ ... ] 범위 직접 추출
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    return json.loads(text)


def summarize_with_groq(site_name: str, articles: list) -> list:
    """Groq(Llama)로 기사 제목+내용을 한국어 매거진 문체로 요약."""
    if not articles:
        return []

    client = Groq(api_key=GROQ_API_KEY)

    articles_text = "\n".join([
        f"{i+1}. 제목: {a['title']}\n   내용: {a['summary']}"
        for i, a in enumerate(articles)
    ])

    prompt = SUMMARY_STYLE_PROMPT.format(articles_text=articles_text)

    # 무료 플랜 RPM 제한 대응 (30 RPM)
    time.sleep(2)

    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            break
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                print(f"    {model} 한도 초과, 다음 모델 시도...")
                time.sleep(3)
                continue
            raise
    else:
        print(f"    경고: {site_name} 모든 모델 한도 초과, 구글 번역으로 대체")
        return _fallback_translate(articles)

    text = response.choices[0].message.content.strip()

    try:
        parsed = _extract_json(repair_json(text))
    except (json.JSONDecodeError, ValueError):
        print(f"    경고: {site_name} 파싱 실패, 구글 번역으로 대체")
        return _fallback_translate(articles)

    result = []
    for i, article in enumerate(articles):
        item = parsed[i] if i < len(parsed) else {}
        result.append({
            **article,
            "korean_title": _sanitize_korean(item.get("korean_title", article["title"])),
            "korean_summary": _sanitize_korean(item.get("korean_summary", article["summary"])),
        })
    return result


def filter_articles_by_category(site_name: str, articles: list, category: dict) -> list:
    """2단계 필터링: 1차 키워드 매칭 → 2차 Groq AI 판단."""
    if not articles:
        return []

    keywords = [k.lower() for k in category.get("keywords", [])]
    exclude_keywords = [k.lower() for k in category.get("exclude_keywords", [])]
    category_label = category["label"]

    passed, needs_ai = [], []
    for article in articles:
        haystack = (article["title"] + " " + article["summary"]).lower()
        # 제목에 제외 키워드가 있으면 즉시 탈락
        title_lower = article["title"].lower()
        if exclude_keywords and any(ex in title_lower for ex in exclude_keywords):
            continue
        if any(kw in haystack for kw in keywords):
            passed.append(article)
        else:
            needs_ai.append(article)

    # 2차: Groq AI 판단
    if needs_ai:
        category_defs = (
            "home=주거공간/주택/인테리어, furniture=가구/조명/프로덕트, "
            "office=오피스/상업공간/호스피탈리티, trend=트렌드/소재/건축/전시"
        )
        articles_text = "\n".join([
            f"{i+1}. {a['title']} — {a['summary'][:120]}"
            for i, a in enumerate(needs_ai)
        ])
        prompt = (
            f"다음 기사들이 [{category_label}] 카테고리에 해당하는지 각각 판단해줘.\n"
            f"카테고리 정의: {category_defs}\n\n"
            f"기사 목록:\n{articles_text}\n\n"
            f"반드시 JSON 배열로만 답해줘: "
            f'[{{"index": 1, "match": true}}, ...]'
        )
        try:
            client = Groq(api_key=GROQ_API_KEY)
            time.sleep(2)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            result = _extract_json(repair_json(response.choices[0].message.content.strip()))
            match_set = {r["index"] for r in result if r.get("match")}
            for i, article in enumerate(needs_ai, start=1):
                if i in match_set:
                    passed.append(article)
        except Exception:
            pass  # AI 판단 실패 시 해당 기사들은 탈락

    final = passed[:5]
    original_count = len(articles)
    if len(final) < original_count:
        print(f"    {site_name}: {original_count}개 → {len(final)}개 (필터링됨)")
    return final


def _fallback_translate(articles: list) -> list:
    """Gemini 실패 시 구글 번역으로 대체."""
    result = []
    for article in articles:
        try:
            kt = GoogleTranslator(source="auto", target="ko").translate(article["title"][:4999])
            ks = GoogleTranslator(source="auto", target="ko").translate(article["summary"][:4999])
        except Exception:
            kt, ks = article["title"], article["summary"]
        result.append({**article, "korean_title": kt, "korean_summary": ks})
    return result


def generate_html_newsletter(translated_data: dict, output_path: str, category_label: str = "글로벌 트렌드", category_key: str = "home"):
    today = datetime.now().strftime("%Y년 %m월 %d일")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    colors = CATEGORY_COLORS.get(category_key, {"primary": "#111827", "light": "#f3f4f6"})
    color_primary = colors["primary"]
    color_light = colors["light"]

    site_sections_html = ""
    for site_name, articles in translated_data.items():
        if not articles:
            continue

        cards_html = ""
        for article in articles:
            image_url = article.get("image_url", "")
            img_html = ""
            if image_url and image_url.startswith("http") and "placeholder" not in image_url:
                img_html = f'<tr><td><img src="{image_url}" width="100%" style="display:block; max-height:220px; object-fit:cover;" alt=""></td></tr>'
            cards_html += f"""
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px; border:1px solid #e5e7eb; border-left:4px solid {color_primary}; border-radius:8px; overflow:hidden;">
              {img_html}
              <tr>
                <td style="padding:16px 20px;">
                  <span style="display:inline-block; background:{color_light}; color:{color_primary}; font-size:11px; font-weight:700; padding:3px 8px; border-radius:4px; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:10px;">{site_name}</span>
                  <p style="margin:0 0 8px 0; font-size:16px; font-weight:700; color:#111827; line-height:1.4;">{article['korean_title']}</p>
                  <p style="margin:0 0 12px 0; font-size:14px; color:#4b5563; line-height:1.8;">{article['korean_summary']}</p>
                  <a href="{article['link']}" style="font-size:13px; color:{color_primary}; text-decoration:none; font-weight:600;">원문 보기 &rarr;</a>
                </td>
              </tr>
            </table>"""

        site_sections_html += f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:40px;">
          <tr>
            <td style="padding:12px 0 16px 0; border-bottom:2px solid {color_primary};">
              <span style="font-size:13px; font-weight:700; color:{color_primary}; letter-spacing:0.08em; text-transform:uppercase;">{site_name}</span>
            </td>
          </tr>
          <tr>
            <td style="padding-top:20px;">
              {cards_html}
            </td>
          </tr>
        </table>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>가구백서 글로벌 트렌드 뉴스레터 - {today}</title>
</head>
<body style="margin:0; padding:0; background-color:#f3f4f6; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6; padding:40px 0;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; overflow:hidden;">
          <tr>
            <td style="background-color:{color_primary}; padding:36px 40px;">
              <p style="margin:0 0 6px 0; font-size:12px; font-weight:600; color:rgba(255,255,255,0.6); letter-spacing:0.1em; text-transform:uppercase;">Global Furniture & Space Trends</p>
              <h1 style="margin:0 0 8px 0; font-size:26px; font-weight:800; color:#ffffff; line-height:1.2;">가구백서 — {category_label}</h1>
              <p style="margin:0; font-size:14px; color:rgba(255,255,255,0.7);">{today}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 40px 12px 40px; border-bottom:1px solid #f3f4f6;">
              <p style="margin:0; font-size:14px; color:#6b7280; line-height:1.7;">
                전 세계 주요 디자인 미디어에서 엄선한 최신 가구·공간 트렌드를 정리했습니다.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 40px;">
              {site_sections_html}
            </td>
          </tr>
          <tr>
            <td style="background-color:#f9fafb; padding:24px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-size:12px; color:#9ca3af; text-align:center;">
                가구백서 뉴스레터 &middot; 자동 생성: {generated_at}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML 뉴스레터 저장: {output_path}")


def send_to_slack(translated_data: dict, html_filename: str, category_label: str = "글로벌 트렌드"):
    if not SLACK_WEBHOOK_URL:
        print("  Slack Webhook URL이 .env에 없어 전송 건너뜀")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"가구백서 {category_label} — {today}"}
        },
        {"type": "divider"},
    ]

    for site_name, articles in translated_data.items():
        if not articles:
            continue
        if len(blocks) > 45:
            break

        # 사이트명 context
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*[ {site_name} ]*"}]
        })

        for i, article in enumerate(articles[:3]):
            if len(blocks) > 45:
                break

            summary_short = article["korean_summary"].split(".")[0] + "."
            image_url = article.get("image_url", "")

            # 이미지는 첫 번째 기사만 (블록 수 절약)
            if i == 0 and image_url and image_url.startswith("http") and "placeholder" not in image_url:
                blocks.append({
                    "type": "image",
                    "image_url": image_url,
                    "alt_text": article["korean_title"][:2000]
                })

            # 제목 + 요약
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{article['korean_title']}*\n{summary_short}"
                }
            })

            # 원문 보기 버튼
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "→ 원문 보기"},
                        "url": article["link"],
                        "style": "primary"
                    }
                ]
            })

        blocks.append({"type": "divider"})

    # 하단 context
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"📄 `{html_filename}` | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        ]
    })

    response = requests.post(
        SLACK_WEBHOOK_URL,
        json={"blocks": blocks},
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    if response.status_code == 200:
        print("  Slack 전송 완료")
    else:
        print(f"  Slack 전송 실패: {response.status_code} {response.text}")


def run_newsletter_pipeline():
    # 카테고리 결정: CLI 인자 우선, 없으면 오늘 요일 기준 자동 선택
    if len(sys.argv) > 1:
        category_key = sys.argv[1]
        if category_key not in CATEGORY_FEEDS:
            print(f"알 수 없는 카테고리: {category_key}")
            print(f"가능한 값: {list(CATEGORY_FEEDS.keys())}")
            sys.exit(1)
    else:
        today_weekday = datetime.now().weekday()
        category_key = next(
            (k for k, v in CATEGORY_FEEDS.items() if v["day"] == today_weekday),
            None
        )
        if category_key is None:
            sys.exit(0)

    category = CATEGORY_FEEDS[category_key]
    category_label = category["label"]
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"가구백서 뉴스레터 — {category_label}")
    print("=" * 60)

    # 이미 전송된 URL 로드
    sent_urls = load_sent_urls()
    if sent_urls:
        print(f"  (중복 제거: 최근 {SENT_EXPIRY_DAYS}일 내 전송된 기사 {len(sent_urls)}개 제외 대상)")

    print("\n[1/4] RSS 피드 수집 중...")
    raw_data = scrape_newsletter_trends(category_key)

    # 이미 전송된 기사 제거
    for site_name in raw_data:
        before = len(raw_data[site_name])
        raw_data[site_name] = [a for a in raw_data[site_name] if a["link"] not in sent_urls]
        removed = before - len(raw_data[site_name])
        if removed:
            print(f"  {site_name}: 중복 {removed}개 제거됨")

    print("\n[2/4] 카테고리 필터링 중...")
    filtered_data = {}
    for site_name, articles in raw_data.items():
        filtered_data[site_name] = filter_articles_by_category(site_name, articles, category)

    print("\n[3/4] Groq AI 한국어 요약 중...")
    translated_data = {}
    for site_name, articles in filtered_data.items():
        if not articles:
            translated_data[site_name] = []
            continue
        print(f"  {site_name} 요약 중...")
        translated_data[site_name] = summarize_with_groq(site_name, articles)

    translated_file = f"translated_report_{category_key}.json"
    with open(translated_file, "w", encoding="utf-8") as f:
        json.dump(translated_data, f, ensure_ascii=False, indent=4)
    print(f"  결과 저장: {translated_file}")

    print("\n[4/4] 뉴스레터 생성 및 Slack 전송 중...")
    html_filename = f"newsletter_{category_key}_{today_str}.html"
    generate_html_newsletter(translated_data, html_filename, category_label, category_key)
    send_to_slack(translated_data, html_filename, category_label)

    # 전송된 기사 URL 저장 (다음 실행 시 중복 방지)
    all_sent = [a["link"] for articles in translated_data.values() for a in articles if a.get("link")]
    if all_sent:
        save_sent_urls(sent_urls, all_sent)
        print(f"  중복 방지 등록: {len(all_sent)}개 URL → {SENT_ARTICLES_FILE}")

    print("\n" + "=" * 60)
    print(f"완료! 생성된 파일: {html_filename}")
    print("=" * 60)


if __name__ == "__main__":
    run_newsletter_pipeline()
