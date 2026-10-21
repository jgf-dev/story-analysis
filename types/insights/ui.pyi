from typing import Literal
from _typeshed import Incomplete

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

PASS: Literal['PASS'] = "PASS"
BASE: Literal['<!doctype html><html><head><meta charset="utf-8">\n<title>JGF Story Insight Platform</title>\n<style>\n body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e7e9ee}\n a{color:#7cb8ff;text-decoration:none} a:hover{text-decoration:underline}\n header{background:#161a22;padding:14px 24px;border-bottom:1px solid #262c38;display:flex;gap:22px;align-items:center}\n header h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.4px}\n header nav{display:flex;gap:16px;font-size:14px}\n main{padding:24px;max-width:1180px;margin:0 auto}\n .cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:22px}\n .card{background:#161a22;border:1px solid #262c38;border-radius:10px;padding:14px 18px;min-width:150px}\n .card .k{color:#8b93a7;font-size:12px;text-transform:uppercase;letter-spacing:.5px}\n .card .v{font-size:22px;font-weight:600;margin-top:4px}\n table{border-collapse:collapse;width:100%;font-size:14px}\n th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #222833}\n th{color:#8b93a7;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.4px}\n .grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}\n .panel{background:#161a22;border:1px solid #262c38;border-radius:10px;padding:16px 18px;margin-bottom:20px}\n .panel h3{margin:0 0 12px;font-size:14px;color:#c7cddb;font-weight:600}\n .chip{display:inline-block;background:#202737;border:1px solid #2c3547;border-radius:999px;padding:3px 10px;margin:3px 4px 3px 0;font-size:12px}\n .badge{display:inline-block;padding:1px 7px;border-radius:5px;font-size:11px;border:1px solid #2c3547}\n .t1{background:#12351f;border-color:#1f6b3a} .t2{background:#1c2f45;border-color:#2f5d8a}\n .t3{background:#3a3216;border-color:#7a681f} .t4{background:#3a1717;border-color:#7a1f1f}\n input[type=text]{background:#0f1115;border:1px solid #2c3547;color:#e7e9ee;padding:9px 12px;border-radius:8px;font-size:14px;width:420px}\n select,button{background:#202737;border:1px solid #2c3547;color:#e7e9ee;padding:7px 12px;border-radius:8px;font-size:13px}\n button{cursor:pointer;background:#2b5fd9;border-color:#2b5fd9}\n .mut{color:#8b93a7;font-size:12px} .sim{color:#7cd98a;font-variant-numeric:tabular-nums}\n audio{width:100%;margin-top:8px}\n .facetrow{margin-bottom:10px}\n .facetrow label{display:block;color:#8b93a7;font-size:12px;margin-bottom:5px}\n .bar{display:inline-block;height:11px;background:#2b5fd9;border-radius:2px;vertical-align:middle}\n</style></head><body>\n<header><h1>JGF · Story Insight Platform</h1>\n<nav><a href="/">Dashboard</a><a href="/search">Semantic search</a><a href="/combo">Combo search (NER)</a></nav>\n<span class="mut" style="margin-left:auto">internal · reference-only corpus</span></header>\n<main>{{ body|safe }}</main></body></html>'] = ("""<!doctype html><html><head><meta charset="utf-8">
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
<main>{{ body|safe }}</main></body></html>""")


class InsightApp:
    app: Flask
    db_path: str
    out_dir: str

    def __init__(self, db_path: str, out_dir: str) -> Incomplete: ...

    def conn(self) -> sqlite3.Connection: ...

    def analysis(self) -> Dict[str, Any]: ...

    def clusters(self) -> List[Dict[str, Any]]: ...


def create_app(db_path: str, out_dir: str) -> Flask: ...


def main(argv: Optional[List[str]] = None) -> None: ...
