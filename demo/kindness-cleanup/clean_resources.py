"""Rescue a messy community resource list. Standard library only, no network.

Usage: python3 clean_resources.py INPUT.csv [--enrich enrich.json] [--out out]
Writes: cleaned_resources.csv, NEWCOMER_GUIDE.md, needs_review.csv, cleaning_report.md
"""
import argparse
import csv
import json
import re

CATEGORIES = ["Getting Started", "Tutorials", "Events", "Community", "Tools", "Reference"]
SYNONYMS = {
    "getting started": "Getting Started", "start": "Getting Started", "setup": "Getting Started",
    "onboarding": "Getting Started", "welcome": "Getting Started",
    "tutorials": "Tutorials", "tutorial": "Tutorials", "how-to": "Tutorials", "howto": "Tutorials",
    "guides": "Tutorials", "guide": "Tutorials", "video": "Tutorials", "videos": "Tutorials",
    "projects": "Tutorials", "learning": "Tutorials",
    "events": "Events", "event": "Events", "meetups": "Events", "meetup": "Events", "office hours": "Events",
    "community": "Community", "chat": "Community", "forum": "Community", "mentoring": "Community",
    "mentorship": "Community", "policy": "Community", "policies": "Community",
    "tools": "Tools", "tool": "Tools", "cheatsheets": "Tools", "cheatsheet": "Tools", "hosting": "Tools",
    "reference": "Reference", "docs": "Reference", "documentation": "Reference", "glossary": "Reference",
}
TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src)$", re.I)
URL_RE = re.compile(r"^(https?)://([a-z0-9-]+(\.[a-z0-9-]+)+)(:\d+)?(/[^\s]*)?$", re.I)


def squash(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_url(raw):
    """Return (clean_url, note). clean_url is '' when the link is not usable."""
    raw = squash(raw)
    note = []
    if raw and "://" not in raw and re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", raw, re.I):
        raw, note = "https" + "://" + raw, ["added https"]
    m = URL_RE.match(raw)
    if not m:
        return "", ""
    scheme, host, _, port, rest = m.group(1).lower(), m.group(2).lower(), m.group(3), m.group(4) or "", m.group(5) or ""
    if host.startswith("www."):
        host = host[4:]
    rest = rest.split("#", 1)[0]
    path, _, query = rest.partition("?")
    kept = [p for p in query.split("&") if p and not TRACKING.match(p.split("=", 1)[0])]
    if len(kept) != len([p for p in query.split("&") if p]):
        note.append("removed tracking")
    path = path.rstrip("/")
    url = f"{scheme}://{host}{port}{path}" + ("?" + "&".join(kept) if kept else "")
    if scheme == "http":
        note.append("http link, check for https")
    return url, "; ".join(note)


def dedupe_key(url):
    m = URL_RE.match(url)
    return (m.group(2).lower() + (m.group(5) or "")).rstrip("/") if m else url


def pick_category(raw, enrich_cat):
    key = squash(raw).lower()
    if key in SYNONYMS:
        return SYNONYMS[key], "rule"
    if enrich_cat in CATEGORIES:
        return enrich_cat, "model"
    return "Reference", "default"


def fallback_tip(name, desc):
    return (desc.rstrip(".") + ".") if desc else f"Open {name} to see what it offers."


def clean(rows, enrich):
    kept, review, removed = {}, [], []
    for i, row in enumerate(rows, start=2):
        name, desc = squash(row.get("name")), squash(row.get("description"))
        if not any(squash(v) for v in row.values()):
            removed.append((i, "(empty row)", "blank row"))
            continue
        url, note = normalize_url(row.get("url"))
        if not url:
            removed.append((i, name or "(no title)", "link is not a valid web address"))
            continue
        if not name:
            review.append({"line": i, "url": url, "category": squash(row.get("category")), "description": desc,
                           "why": "missing title: a person should name it"})
            continue
        key = dedupe_key(url)
        name_key = re.sub(r"[^a-z0-9]", "", name.lower())
        info = enrich.get(name_key, {})
        cat, how = pick_category(row.get("category"), info.get("category"))
        item = {"name": name, "url": url, "category": cat, "description": desc, "note": note, "how": how,
                "tip": squash(info.get("tip")) or fallback_tip(name, desc), "level": info.get("level", ""),
                "name_key": name_key, "line": i}
        dup = kept.get(key) or next((k for k in kept.values() if k["name_key"] == name_key), None)
        if dup:
            loser, winner = (item, dup) if len(desc) <= len(dup["description"]) else (dup, item)
            if winner["url"].startswith("http:") and loser["url"].startswith("https:"):
                winner["url"] = loser["url"]  # prefer the secure link when two rows point to the same page
                winner["note"] = "; ".join(x for x in winner["note"].split("; ") if x and not x.startswith("http link"))
            if winner is item:
                kept.pop(dedupe_key(dup["url"]), None)
                kept[key] = item
            removed.append((loser["line"], loser["name"], f"duplicate of '{winner['name']}'"))
            continue
        kept[key] = item
    still_review = []
    for r in review:  # a row with no title is only worth a human's time if its link is not already covered
        twin = kept.get(dedupe_key(r["url"]))
        if twin:
            removed.append((r["line"], "(no title)", f"same link as '{twin['name']}', which is already listed"))
        else:
            still_review.append(r)
    review = still_review
    items = sorted(kept.values(), key=lambda x: (CATEGORIES.index(x["category"]), x["name"].lower()))
    for n, it in enumerate(items, 1):
        it["id"] = f"r{n:02d}"
    return items, review, removed


def write_outputs(items, review, removed, total, out):
    with open(out + "/cleaned_resources.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "url", "category", "newcomer_tip", "level", "start_here", "check_note"])
        for it in items:
            w.writerow([it["id"], it["name"], it["url"], it["category"], it["tip"], it["level"],
                        "yes" if it["category"] == "Getting Started" else "", it["note"]])
    with open(out + "/needs_review.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["line", "url", "category", "description", "why"])
        w.writeheader()
        w.writerows(review)
    lines = ["# Welcome! Your friendly resource list", "",
             "Not sure where to begin? Start with the first section, then pick what you need.", ""]
    for cat in CATEGORIES:
        group = [it for it in items if it["category"] == cat]
        if not group:
            continue
        lines += [f"## {'Start here: ' if cat == 'Getting Started' else ''}{cat}", ""]
        for it in group:
            lvl = f" _({it['level']})_" if it["level"] else ""
            lines.append(f"- [{it['name']}]({it['url']}){lvl}: {it['tip']}")
        lines.append("")
    lines += ["---", "Something missing or broken? Tell a maintainer. Everyone started as a newcomer."]
    with open(out + "/NEWCOMER_GUIDE.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    rep = ["# Cleaning report", "", f"- rows in: {total}", f"- clean rows out: {len(items)}",
           f"- removed: {len(removed)}", f"- sent to a human (needs_review.csv): {len(review)}", "", "## Removed", ""]
    rep += [f"- line {ln}: {nm}: {why}" for ln, nm, why in removed] or ["- nothing"]
    rep += ["", "## Notes on kept rows", ""]
    rep += [f"- {it['name']}: {it['note']}" for it in items if it["note"]] or ["- none"]
    rep += ["", "## Categories decided by", ""]
    for how in ("rule", "model", "default"):
        rep.append(f"- {how}: {sum(1 for it in items if it['how'] == how)}")
    with open(out + "/cleaning_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--enrich", default="")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    with open(a.source, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    enrich = {}
    if a.enrich:
        with open(a.enrich, "r", encoding="utf-8") as f:
            enrich = json.load(f)
    items, review, removed = clean(rows, enrich)
    write_outputs(items, review, removed, len(rows), a.out)
    print(json.dumps({"rows_in": len(rows), "rows_out": len(items), "removed": len(removed), "needs_review": len(review)}))


main()
