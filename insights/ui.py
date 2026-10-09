"""Internal research web UI for the story catalogue (JGF-12).

Local-only Flask app served on 127.0.0.1. Pages:
  /                stats dashboard (distributions, trends, clusters)
  /search?q=       semantic search over Tier-1/2 candidates
  /combo           NER combination search (trope x setting x character x ...)
  /story/<id>      story detail + cheap local TTS audition

The dataset is internal reference material: this UI is not deployed publicly
and never distributes dataset content outside the company.
"""

from __future__ import annotations

import html
import json
import os
import sqlite3
import zlib
from typing import Any, Dict, List, Optional

from flask import Flask, Response, abort, redirect, render_template_string, request, url_for

from insights import ner as ner_mod
from insights import tts_audition

PASS = "PASS"

BASE = """<!doctype html><html><head><meta charset="utf-8">
<title>JGF Story Insight Platform</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e7e9ee}
 a{color:#7cb8ff;text-decoration:none} a:hover{text-decoration:underline}
 header{background:#161a22;padding:14px 24px;border-bottom:1px solid #262c38;display:flex;gap:22px;align-items:center}
 header h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.4px}
 header nav{display:flex;gap:16px;font-size:14px}
 main{padding:24px;max-width:1180px;margin:0 auto}
 .cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:22px}
 .card{background:#161a22;border:1px solid #262c38;border-radius:10px;padding:14px 18px;min-width:150px}
 .card .k{color:#8b93a7;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
 .card .v{font-size:22px;font-weight:600;margin-top:4px}
 table{border-collapse:collapse;width:100%;font-size:14px}
 th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #222833}
 th{color:#8b93a7;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}
 .panel{background:#161a22;border:1px solid #262c38;border-radius:10px;padding:16px 18px;margin-bottom:20px}
 .panel h3{margin:0 0 12px;font-size:14px;color:#c7cddb;font-weight:600}
 .chip{display:inline-block;background:#202737;border:1px solid #2c3547;border-radius:999px;padding:3px 10px;margin:3px 4px 3px 0;font-size:12px}
 .badge{display:inline-block;padding:1px 7px;border-radius:5px;font-size:11px;border:1px solid #2c3547}
 .t1{background:#12351f;border-color:#1f6b3a} .t2{background:#1c2f45;border-color:#2f5d8a}
 .t3{background:#3a3216;border-color:#7a681f} .t4{background:#3a1717;border-color:#7a1f1f}
 input[type=text]{background:#0f1115;border:1px solid #2c3547;color:#e7e9ee;padding:9px 12px;border-radius:8px;font-size:14px;width:420px}
 select,button{background:#202737;border:1px solid #2c3547;color:#e7e9ee;padding:7px 12px;border-radius:8px;font-size:13px}
 button{cursor:pointer;background:#2b5fd9;border-color:#2b5fd9}
 .mut{color:#8b93a7;font-size:12px} .sim{color:#7cd98a;font-variant-numeric:tabular-nums}
 audio{width:100%;margin-top:8px}
 .facetrow{margin-bottom:10px}
 .facetrow label{display:block;color:#8b93a7;font-size:12px;margin-bottom:5px}
 .bar{display:inline-block;height:11px;background:#2b5fd9;border-radius:2px;vertical-align:middle}
</style></head><body>
<header><h1>JGF · Story Insight Platform</h1>
<nav><a href="/">Dashboard</a><a href="/search">Semantic search</a><a href="/combo">Combo search (NER)</a></nav>
<span class="mut" style="margin-left:auto">internal · reference-only corpus</span></header>
<main>{{ body|safe }}</main></body></html>"""


def _page(title: str, body: str) -> str:
    return render_template_string(BASE, body=f"<h2 style='margin-top:0'>{title}</h2>{body}")


def _bars(items: List[List[Any]], max_bars: int = 14, width: int = 520) -> str:
    if not items:
        return "<p class='mut'>no data</p>"
    items = items[:max_bars]
    top = max((v for _, v in items), default=1) or 1
    rows = []
    for label, value in items:
        pct = int(100 * value / top)
        rows.append(
            "<div style='margin:3px 0'><span style='display:inline-block;width:200px'>"
            f"{html.escape(str(label))}</span>"
            f"<span class='bar' style='width:{pct*2.4:.0f}px'></span>"
            f"<span class='mut' style='margin-left:8px'>{value}</span></div>")
    return "".join(rows)


def _tier_badge(tier: str) -> str:
    cls = {"Tier 1: Master Candidate": "t1", "Tier 2: Good Secondary": "t2",
           "Tier 3: Needs Polishing": "t3", "Tier 4: Reject / Low Quality": "t4"}.get(tier, "")
    return f"<span class='badge {cls}'>{html.escape(tier.split(':')[0])}</span>"


class InsightApp:
    def __init__(self, db_path: str, out_dir: str):
        self.db_path = db_path
        self.out_dir = out_dir
        self.app = Flask(__name__)
        self._analysis_cache: Dict[str, Any] = {}
        self._register_routes()

    # -- helpers -----------------------------------------------------------
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def analysis(self) -> Dict[str, Any]:
        path = os.path.join(self.out_dir, "analysis", "analysis.json")
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if self._analysis_cache.get("mtime") != mtime:
                self._analysis_cache = {"mtime": mtime, "data": json.load(open(path))}
            return self._analysis_cache["data"]
        return {}

    def clusters(self) -> List[Dict[str, Any]]:
        path = os.path.join(self.out_dir, "clusters.json")
        return json.load(open(path)) if os.path.exists(path) else []

    def _searcher(self):
        if not hasattr(self, "_sem"):
            from insights.semantic import SemanticSearcher
            self._sem = SemanticSearcher(self.out_dir)
        return self._sem

    def _story_rows(self, ids: List[int]) -> Dict[int, Dict[str, Any]]:
        if not ids:
            return {}
        q = f"SELECT * FROM stories WHERE id IN ({','.join('?'*len(ids))})"
        with self.conn() as c:
            return {r["id"]: dict(r) for r in c.execute(q, ids)}

    # -- routes ------------------------------------------------------------
    def _register_routes(self):
        app = self.app

        @app.get("/")
        def index():
            a = self.analysis()
            if not a:
                body = ("<p>Analysis not generated yet. Run:<br><code>"
                        "python -m insights.analysis --db data/catalog.sqlite</code></p>"
                        "<p>Ingest status below.</p>" + self._ingest_panel())
                return _page("Dashboard", body)
            s = a["summary"]
            dist = a["distributions"]
            cards = [
                ("canonical stories", f"{s['canonical_stories']:,}"),
                ("duplicate rows removed", f"{s['duplicate_rows']:,}"),
                ("safety-passing", f"{s['passing_stories']:,}"),
                ("Tier 1 master candidates",
                 f"{s['canonical_tiers'].get('Tier 1: Master Candidate', 0):,}"),
                ("catalogue words", f"{s['passing_words']:,}"),
                ("audio-hours available", f"{s['passing_audio_hours']:,}"),
                ("distinct authors", f"{s['distinct_authors']:,}"),
                ("date range", f"{s['date_range'][0] or '?'}–{s['date_range'][1] or '?'}"),
            ]
            cards_html = "".join(
                f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div></div>"
                for k, v in cards)
            trends = a.get("trends", {}).get("yearly", [])
            trend_items = [[r["year"], r["stories"]] for r in trends
                           if int(r["year"]) >= 1995][-20:]
            body = f"<div class='cards'>{cards_html}</div>"
            body += "<div class='grid2'>"
            body += f"<div class='panel'><h3>Top tropes</h3>{_bars(dist.get('tropes', []))}</div>"
            body += f"<div class='panel'><h3>Categories</h3>{_bars(dist.get('category', []))}</div>"
            body += f"<div class='panel'><h3>Heat levels</h3>{_bars(dist.get('heat', []))}</div>"
            body += f"<div class='panel'><h3>Pacing</h3>{_bars(dist.get('pacing', []))}</div>"
            body += f"<div class='panel'><h3>Story volume by year</h3>{_bars(trend_items)}</div>"
            body += f"<div class='panel'><h3>Length buckets</h3>{_bars(dist.get('length_buckets', []))}</div>"
            body += "</div>"
            clusters = self.clusters()
            if clusters:
                rows = []
                for c in clusters[:20]:
                    terms = ", ".join(c["top_terms"][:6])
                    ex = c["exemplars"][0] if c["exemplars"] else {}
                    link = f"<a href='/story/{ex['id']}'>{html.escape(ex.get('title','?')[:48])}</a>"
                    rows.append(f"<tr><td>{c['cluster']}</td><td>{c['size']:,}</td>"
                                f"<td>{html.escape(terms)}</td><td>{link}</td></tr>")
                body += ("<div class='panel'><h3>Topic clusters (semantic)</h3><table>"
                         "<tr><th>#</th><th>size</th><th>top terms</th><th>exemplar</th></tr>"
                         + "".join(rows) + "</table></div>")
            return _page("Corpus dashboard", body)

        @app.get("/search")
        def search():
            q = request.args.get("q", "").strip()
            results_html = ""
            if q:
                hits = []
                try:
                    hits = self._searcher().search(q, top_k=20)
                    rows_map = self._story_rows([h["id"] for h in hits])
                    arr = []
                    for h in hits:
                        st = rows_map.get(h["id"])
                        if not st:
                            continue
                        tropes = "".join(f"<span class='chip'>{html.escape(t)}</span>"
                                         for t in json.loads(st["tropes"] or "[]"))
                        arr.append(
                            f"<tr><td class='sim'>{h['similarity']:.3f}</td>"
                            f"<td><a href='/story/{st['id']}'>{html.escape(st['title'][:70])}</a>"
                            f"<div class='mut'>{html.escape(st['category'])} · "
                            f"{st['publication_date'][:4]} · {st['word_count']:,}w · "
                            f"{_tier_badge(st['quality_tier'])}</div></td>"
                            f"<td>{tropes}</td></tr>")
                    results_html = ("<table><tr><th>sim</th><th>story</th><th>tropes</th></tr>"
                                    + "".join(arr) + "</table>")
                    if not arr:
                        results_html = "<p>No in-scope candidates matched (Tier 1/2, safety-passing).</p>"
                except FileNotFoundError:
                    results_html = ("<p class='mut'>Semantic index not built yet. Run "
                                    "<code>python -m insights.semantic --db data/catalog.sqlite</code>.</p>")
            body = (f"<form action='/search' method='get'>"
                    f"<input type='text' name='q' value='{html.escape(q)}' "
                    f"placeholder='e.g. &quot;older construction worker and shy college jock slow burn&quot;'>"
                    f" <button>Search</button></form>"
                    f"<p class='mut'>Embeddings: TF-IDF + SVD over title + preview of Tier 1/2 "
                    f"candidates. Local, deterministic, zero-cost.</p>{results_html}")
            return _page("Semantic search", body)

        @app.get("/combo")
        def combo():
            selected: Dict[str, List[str]] = {}
            for key in ("setting", "character", "dynamic", "topic"):
                selected[key] = request.args.getlist(key)
            category = request.args.get("category", "").strip()
            era = request.args.get("era", "").strip()
            min_w = request.args.get("min_words", "").strip()
            filters = {k: v for k, v in selected.items() if v}
            extra_where, extra_args = "", []
            if category:
                extra_where += (" AND s.category=?" if extra_where else "s.category=?")
                extra_args.append(category)
            if era and era.isdigit():
                extra_where += (" AND substr(s.publication_date,1,4)>=?" if extra_where
                                else "substr(s.publication_date,1,4)>=?")
                extra_args.append(era)
            if min_w.isdigit():
                extra_where += (" AND s.word_count>=?" if extra_where else "s.word_count>=?")
                extra_args.append(int(min_w))
            try:
                total = ner_mod.combo_count(self.db_path, filters, extra_where, tuple(extra_args))
                rows = ner_mod.combo_search(self.db_path, filters, extra_where,
                                            tuple(extra_args), limit=50)
            except sqlite3.OperationalError:
                msg = ("<p class='mut'>NER entities not built yet. Run "
                       "<code>python -m insights.ner --db data/catalog.sqlite</code>.</p>")
                return _page("NER combination search", msg)

            def facet_block(etype, title):
                try:
                    counts = ner_mod.facet_counts(self.db_path, etype, filters)
                except sqlite3.OperationalError:
                    counts = []
                boxes = []
                for label, n in counts[:30]:
                    checked = "checked" if label in selected.get(etype, []) else ""
                    boxes.append(
                        f"<label style='display:inline-block;margin:2px 10px;font-size:13px'>"
                        f"<input type='checkbox' name='{etype}' value='{html.escape(label)}' {checked}> "
                        f"{html.escape(label)} <span class='mut'>({n})</span></label>")
                return f"<div class='facetrow'><label>{title}</label>{''.join(boxes)}</div>"

            with self.conn() as c:
                cats = [r[0] for r in c.execute(
                    "SELECT category, count(*) n FROM stories WHERE is_canonical=1 "
                    "AND safety_verdict='PASS' GROUP BY category ORDER BY n DESC LIMIT 40")]
            cat_opts = "".join(
                f"<option value='{html.escape(x)}' {'selected' if x==category else ''}>"
                f"{html.escape(x)}</option>" for x in cats)
            table = []
            for r in rows:
                tropes = "".join(f"<span class='chip'>{html.escape(t)}</span>"
                                 for t in json.loads(r["tropes"] or "[]")[:3])
                table.append(f"<tr><td><a href='/story/{r['id']}'>{html.escape(r['title'][:66])}</a>"
                             f"<div class='mut'>{html.escape(r['category'])} · {r['year'][:4]} · "
                             f"{r['words']:,}w · {_tier_badge(r['tier'])}</div></td>"
                             f"<td>{tropes}</td></tr>")
            body = (f"<form action='/combo' method='get'>"
                    f"{facet_block('setting','Setting')}{facet_block('character','Character type')}"
                    f"{facet_block('dynamic','Dynamic / trope')}"
                    f"<div class='facetrow'><label>Category "
                    f"<select name='category'><option value=''>any</option>{cat_opts}</select> "
                    f"&nbsp; Published after <input type='text' name='era' size='4' value='{era}' "
                    f"placeholder='1995'> &nbsp; Min words "
                    f"<input type='text' name='min_words' size='5' value='{min_w}'> "
                    f"<button>Apply</button></label></div></form>"
                    f"<p><b>{total:,}</b> matching stories (showing {len(rows)} by quality).</p>"
                    f"<table><tr><th>story</th><th>tropes</th></tr>{''.join(table)}</table>")
            return _page("NER combination search", body)

        @app.get("/story/<int:sid>")
        def story(sid):
            with self.conn() as c:
                row = c.execute("SELECT * FROM stories WHERE id=?", (sid,)).fetchone()
                full = c.execute("SELECT full_text FROM story_text WHERE id=?", (sid,)).fetchone()
            if not row:
                abort(404)
            row = dict(row)
            if full and full[0]:
                text = zlib.decompress(full[0]).decode("utf-8", "replace")[:6000]
            else:
                text = row["preview"] or ""
            tropes = "".join(f"<span class='chip'>{html.escape(t)}</span>"
                             for t in json.loads(row["tropes"] or "[]"))
            arch = "".join(f"<span class='chip'>{html.escape(t)}</span>"
                           for t in json.loads(row["archetypes"] or "[]"))
            sets = "".join(f"<span class='chip'>{html.escape(t)}</span>"
                           for t in json.loads(row["settings"] or "[]"))
            eng = tts_audition.engine_status()
            audio = (f"<audio controls preload='none' src='/story/{sid}/audio'></audio>"
                     if eng["available"] else f"<p class='mut'>{html.escape(eng['note'])}</p>")
            meta = (f"{html.escape(row['author'])} · {html.escape(row['category'])} · "
                    f"{row['publication_date'][:10]} · {row['word_count']:,} words · "
                    f"~{row['tts_minutes']:.0f} min · heat {row['heat_level']} · "
                    f"{html.escape(row['pov'])} · {html.escape(row['pacing'])} · "
                    f"quality {row['quality_total']} {_tier_badge(row['quality_tier'])}")
            safety = (f"<span class='badge t4'>{html.escape(row['safety_verdict'])}</span>"
                      if row["safety_verdict"] != PASS else
                      "<span class='badge t1'>PASS</span>")
            body = (f"<h2 style='margin-bottom:4px'>{html.escape(row['title'])}</h2>"
                    f"<p class='mut'>{meta} · safety {safety}</p>"
                    f"<div class='panel'><h3>Tags</h3><p>{tropes}{arch}{sets}</p></div>"
                    f"<div class='panel'><h3>TTS audition (low-cost local engine)</h3>{audio}"
                    f"<p class='mut'>Audition excerpt for inspiration only — not production audio.</p></div>"
                    f"<div class='panel'><h3>Text excerpt</h3><pre style='white-space:pre-wrap;"
                    f"font-family:inherit;font-size:14px;line-height:1.5'>{html.escape(text)}</pre></div>")
            return _page("Story", body)

        @app.get("/story/<int:sid>/audio")
        def story_audio(sid):
            with self.conn() as c:
                full = c.execute("SELECT full_text FROM story_text WHERE id=?", (sid,)).fetchone()
                row = c.execute("SELECT preview FROM stories WHERE id=?", (sid,)).fetchone()
            text = ""
            if full and full[0]:
                text = zlib.decompress(full[0]).decode("utf-8", "replace")
            elif row:
                text = row[0] or ""
            wav = tts_audition.synthesize(text)
            if not wav:
                abort(503)
            return Response(wav, mimetype="audio/wav",
                            headers={"Cache-Control": "no-store"})

        @app.get("/api/health")
        def health():
            with self.conn() as c:
                n = c.execute("SELECT count(*) FROM stories").fetchone()[0]
            return {"status": "ok", "stories": n,
                    "semantic_index": os.path.exists(os.path.join(self.out_dir, "vectors.npz")),
                    "tts": tts_audition.engine_status()}

    def _ingest_panel(self) -> str:
        try:
            with self.conn() as c:
                n = c.execute("SELECT count(*) FROM stories").fetchone()[0]
                state = c.execute("SELECT value FROM meta WHERE key='ingest_state'").fetchone()
            return f"<div class='panel'><h3>Ingest progress</h3><p>{n:,} rows ingested</p></div>"
        except Exception as e:
            return f"<p class='mut'>{html.escape(str(e))}</p>"


def create_app(db_path: str, out_dir: str) -> Flask:
    return InsightApp(db_path, out_dir).app


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Internal insight UI (JGF-12)")
    p.add_argument("--db", default="data/catalog.sqlite")
    p.add_argument("--out-dir", default="insights_output")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    create_app(args.db, args.out_dir).run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
