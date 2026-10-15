"""D4 step ⑤: download the chosen consolidated audit reports from the DART web site (contract 3.2 step 5).

    python eval/d4_download.py plan --candidates eval/d4_candidates --ranks 5 6 7 ...          # nothing downloaded
    python eval/d4_download.py download --candidates eval/d4_candidates --ranks ... --out ~/Desktop/D4

For each candidate whose ``select`` decision is "받기", ``plan`` reads the filing's DART page, lists its attachments
as DART shows them, and compares them with the names the user recorded (any difference stops that candidate). It
then opens the download window of the chosen attachment and reports the PDF's name (DART gives no size before the
download itself). ``download`` does the
same and saves the PDF, recording every attempt (time, outcome, error kind, SHA-256) in
``<candidates>/downloads.jsonl``. It never retries by itself: the contract's single retry comes at least ten
minutes later, by running it again. The user decided on 2026-10-16 that Claude downloads instead of the user.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from http.cookiejar import CookieJar
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import d4_candidates  # noqa: E402

BASE = "https://dart.fss.or.kr"
HEADERS = {"User-Agent": "Mozilla/5.0 (dart-review-agent D4; one request at a time)"}
EXCLUDED = ROOT / "eval" / "d4_excluded.json"


# DART serves the PDF only within the session of the filing page and its download window (a HEAD request or a
# request without that session is redirected to an error page), so one cookie jar is kept for the whole run.
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _get(url: str, referer: str | None = None) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers=HEADERS | ({"Referer": referer} if referer else {}))
    with _OPENER.open(request, timeout=60) as response:
        return response.read(), dict(response.headers)


def attachments(page: str) -> list[tuple[str, str, str]]:
    """(name as shown, rcpNo, dcmNo) of the attachment select box, in order, without the placeholder. An amended
    filing's page can list attachments that belong to the original filing: their rcpNo is the original's."""
    box = re.search(r'<select id="att".*?</select>', page, re.S)
    if not box:
        return []
    found = []
    for value, text in re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', box.group(0), re.S):
        if value == "null":
            continue
        name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")).strip()
        link = html.unescape(value)
        found.append((name, re.search(r"rcpNo=(\d+)", link).group(1), re.search(r"dcmNo=(\d+)", link).group(1)))
    return found


def _compact(name: str) -> str:
    return re.sub(r"\s+", "", name)


def inspect(record: dict) -> dict:
    """What would be downloaded for one candidate, checked against its record."""
    decision = d4_candidates.select(record, json.loads(EXCLUDED.read_text(encoding="utf-8")))
    out = {"rank": record["rank"], "corp_name": record["corp_name"], "decision": decision["decision"]}
    if decision["decision"] != "받기":
        return out | {"skip": "not 받기"}
    rcept = decision["rcept_no"]
    page = _get(f"{BASE}/dsaf001/main.do?rcpNo={rcept}")[0].decode("utf-8", errors="replace")
    shown = attachments(page)
    recorded = record["attachments"][rcept]
    if [_compact(n) for n, *_ in shown] != [_compact(n) for n in recorded]:
        return out | {"error": "attachment list differs from the record", "shown": [n for n, *_ in shown], "recorded": recorded}
    position = decision["attachment"]["position"]
    name, owner, dcm = shown[position - 1]
    window = f"{BASE}/pdf/download/main.do?rcp_no={owner}&dcm_no={dcm}"
    popup = _get(window)[0].decode("utf-8", errors="replace")
    links = re.findall(r'<td class="tL">([^<]*\.pdf)</td>\s*<td><a class="btnFile" href="([^"]+)"', popup)
    if len(links) != 1:
        return out | {"error": f"expected one PDF in the download window, found {len(links)}"}
    pdf_name, link = links[0]
    return out | {"rcept_no": rcept, "attachment_rcept_no": owner, "dcm_no": dcm, "attachment": name,
                  "pdf_name": html.unescape(pdf_name), "url": BASE + link, "window": window}


def download(item: dict, out_dir: Path) -> dict:
    attempt = {"rank": item["rank"], "corp_name": item["corp_name"], "rcept_no": item["rcept_no"],
               "attachment_rcept_no": item["attachment_rcept_no"], "dcm_no": item["dcm_no"], "pdf_name": item["pdf_name"],
               "url": item["url"], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    target = out_dir / f"{item['rank']:02d}_{item['corp_name']}.pdf"
    if target.exists():
        return attempt | {"outcome": "skipped", "reason": f"{target.name} exists"}
    try:
        data, headers = _get(item["url"], referer=item["window"])
    except urllib.error.HTTPError as exc:
        return attempt | {"outcome": "failed", "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return attempt | {"outcome": "failed", "error": f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"}
    if not data.startswith(b"%PDF"):
        return attempt | {"outcome": "failed", "error": "not a PDF", "content_type": headers.get("Content-Type")}
    target.write_bytes(data)
    return attempt | {"outcome": "saved", "file": target.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("plan", "download"))
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--ranks", type=int, nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "download" and not args.out:
        parser.error("--out is required for download")
    for rank in args.ranks:
        record = json.loads(next(args.candidates.glob(f"{rank:05d}_*.json")).read_text(encoding="utf-8"))
        item = inspect(record)
        if args.command == "plan" or "error" in item or "skip" in item:
            print(json.dumps(item, ensure_ascii=False))
            continue
        args.out.mkdir(parents=True, exist_ok=True)
        attempt = download(item, args.out.expanduser())
        with (args.candidates / "downloads.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(attempt, ensure_ascii=False) + "\n")
        print(json.dumps(attempt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
