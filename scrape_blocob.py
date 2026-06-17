#!/usr/bin/env python3
"""Scrape all 'TEM Bloco B' questions from mfleite.pythonanywhere.com, shuffle them.

Bloco B = area id 1  ->  /questoes_todas/1/0 (paginated via 'Próxima página').
Each question card carries q-id, the text, and options with is-correct="True/False".
"""
import json
import random
import re
import ssl
import sys
import urllib.request
from html.parser import HTMLParser

BASE = "https://mfleite.pythonanywhere.com"
START = "/questoes_todas/1/0"   # 1 = Bloco B
SSL_CTX = ssl._create_unverified_context()


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.read().decode("utf-8", "replace")


class QuestionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.questions = []
        self.cur = None          # current question dict
        self.capture = None      # 'text' | 'option' | None
        self.buf = []
        self.next_page = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and "question" in a:
            self.cur = {"q_id": a.get("q-id"), "area_id": a.get("area-id"),
                        "text": "", "options": []}
        elif tag == "p" and "card-text" in (a.get("class") or "") and self.cur is not None:
            self.capture = "text"; self.buf = []
        elif tag == "a" and "option" in a and self.cur is not None:
            self.capture = "option"; self.buf = []
            self._correct = a.get("is-correct") == "True"
        elif tag == "a" and self.capture is None:
            href = a.get("href", "")
            if re.match(r"/questoes_todas/\d+/\d+$", href):
                self.next_page = href   # last such link on page = Próxima página

    def handle_data(self, data):
        if self.capture:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.capture == "text":
            self.cur["text"] = " ".join("".join(self.buf).split())
            self.capture = None
        elif tag == "a" and self.capture == "option":
            self.cur["options"].append(
                {"text": " ".join("".join(self.buf).split()), "correct": self._correct})
            self.capture = None
        elif tag == "div" and self.cur is not None and self.cur["options"]:
            # close the question card once it has collected its options
            if not any(q["q_id"] == self.cur["q_id"] for q in self.questions):
                self.questions.append(self.cur)
            self.cur = None


def scrape_all():
    seen, all_q, path = set(), [], START
    while path:
        p = QuestionParser()
        p.feed(fetch(path))
        new = [q for q in p.questions if q["q_id"] not in seen]
        for q in new:
            seen.add(q["q_id"])
        all_q.extend(new)
        print(f"  {path}: +{len(new)} (total {len(all_q)})", file=sys.stderr)
        # advance only if next link points somewhere new
        path = p.next_page if (p.next_page and p.next_page != path and new) else None
    return all_q


def main():
    qs = scrape_all()
    random.shuffle(qs)                       # shuffle the questions
    for q in qs:                             # also shuffle options within each
        random.shuffle(q["options"])
    with open("blocob_questions.json", "w", encoding="utf-8") as f:
        json.dump(qs, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(qs)} shuffled questions -> blocob_questions.json", file=sys.stderr)


if __name__ == "__main__":
    main()
