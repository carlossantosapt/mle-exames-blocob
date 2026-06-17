#!/usr/bin/env python3
"""Scrape TEM Bloco B questions per area and emit exam_data.js (embeddable, no CORS)."""
import json
import random
import re
import ssl
import sys
import urllib.request
from html.parser import HTMLParser

BASE = "https://mfleite.pythonanywhere.com"
SSL_CTX = ssl._create_unverified_context()

# friendly category -> list of area ids on the site
CATEGORIES = {
    "pediatria":   [2],
    "ginecologia": [88],
    "obstetricia": [75],
    "decisao":     [102],
    "rest":        [119, 121, 123, 122, 120, 118],
}


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.read().decode("utf-8", "replace")


class QuestionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.questions, self.cur, self.capture, self.buf = [], None, None, []
        self.next_page = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and "question" in a:
            self.cur = {"id": a.get("q-id"), "text": "", "options": []}
        elif tag == "p" and "card-text" in (a.get("class") or "") and self.cur is not None:
            self.capture, self.buf = "text", []
        elif tag == "a" and "option" in a and self.cur is not None:
            self.capture, self.buf = "option", []
            self._correct = a.get("is-correct") == "True"
        elif tag == "a" and self.capture is None:
            if re.match(r"/questoes_todas/\d+/\d+$", a.get("href", "")):
                self.next_page = a["href"]

    def handle_data(self, data):
        if self.capture:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.capture == "text":
            self.cur["text"] = " ".join("".join(self.buf).split()); self.capture = None
        elif tag == "a" and self.capture == "option":
            self.cur["options"].append(
                {"text": " ".join("".join(self.buf).split()), "correct": self._correct})
            self.capture = None
        elif tag == "div" and self.cur is not None and self.cur["options"]:
            if not any(q["id"] == self.cur["id"] for q in self.questions):
                self.questions.append(self.cur)
            self.cur = None


def scrape_area(area_id):
    seen, out, path = set(), [], f"/questoes_todas/{area_id}/0"
    while path:
        p = QuestionParser(); p.feed(fetch(path))
        new = [q for q in p.questions if q["id"] not in seen]
        for q in new:
            seen.add(q["id"])
        out.extend(new)
        path = p.next_page if (p.next_page and p.next_page != path and new) else None
    return out


# fixed-composition exam: questions per category
PLAN = [
    ("pediatria",   75, "Pediatria"),
    ("ginecologia", 20, "Ginecologia"),
    ("obstetricia", 20, "Obstetrícia"),
    ("decisao",     25, "Decisão Terapêutica"),
    ("rest",        10, "Outras áreas"),
]
EXAM_SIZE = sum(n for _, n, _ in PLAN)   # 150
SEED = 20260617                          # fixed -> same exams for everyone


def mkq(q, cat, label):
    opts = q["options"][:]
    random.shuffle(opts)
    out = {"id": q["id"], "cat": cat, "label": label, "text": q["text"], "options": opts}
    if not any(o["correct"] for o in opts):     # no key -> mark; excluded from scoring client-side
        out["noanswer"] = True
    return out


def assemble_exams(pool):
    rng_pos = {cat: 0 for cat in pool}          # cursor per category (shuffled once)
    shuffled = {cat: random.sample(qs, len(qs)) for cat, qs in pool.items()}
    exams = []

    # how many full fixed-composition exams the pools allow
    n_fixed = min(len(pool[c]) // n for c, n, _ in PLAN)
    for i in range(n_fixed):
        qs = []
        for cat, n, label in PLAN:
            chunk = shuffled[cat][rng_pos[cat]:rng_pos[cat] + n]
            rng_pos[cat] += n
            qs += [mkq(q, cat, label) for q in chunk]
        random.shuffle(qs)
        exams.append({"id": i + 1, "type": "fixed", "questions": qs})

    # leftovers -> random-composition exams, no repeats
    leftover = []
    for cat, _, _ in PLAN:
        label = next(l for c, _, l in PLAN if c == cat)
        leftover += [mkq(q, cat, label) for q in shuffled[cat][rng_pos[cat]:]]
    random.shuffle(leftover)
    for j in range(0, len(leftover), EXAM_SIZE):
        exams.append({"id": len(exams) + 1, "type": "random",
                      "questions": leftover[j:j + EXAM_SIZE]})
    return exams


def main():
    random.seed(SEED)
    pool, noanswer = {}, {}
    for cat, areas in CATEGORIES.items():
        qs, ids = [], set()
        for a in areas:
            for q in scrape_area(a):
                if q["id"] not in ids:          # dedup across sub-areas
                    ids.add(q["id"]); qs.append(q)
        pool[cat]     = [q for q in qs if any(o["correct"] for o in q["options"])]      # has a key
        noanswer[cat] = [q for q in qs if not any(o["correct"] for o in q["options"])]  # no key
        print(f"{cat}: {len(pool[cat])} usable, {len(noanswer[cat])} sem resposta", file=sys.stderr)

    exams = assemble_exams(pool)

    # append all key-less questions to the last exam (marked noanswer, mixed in)
    extra = []
    for cat, _, label in PLAN:
        extra += [mkq(q, cat, label) for q in noanswer.get(cat, [])]
    if extra:
        last = exams[-1]
        merged = last["questions"] + extra
        last["questions"] = random.sample(merged, len(merged))
    js = "// auto-generated by build_exam_data.py — do not edit by hand\n"
    js += "window.EXAMS = " + json.dumps(exams, ensure_ascii=False) + ";\n"
    with open("exam_data.js", "w", encoding="utf-8") as f:
        f.write(js)
    for e in exams:
        print(f"  Exame {e['id']} [{e['type']}]: {len(e['questions'])} questões", file=sys.stderr)
    print(f"\nWrote exam_data.js ({len(exams)} exams, "
          f"{sum(len(e['questions']) for e in exams)} questions)", file=sys.stderr)


if __name__ == "__main__":
    main()
