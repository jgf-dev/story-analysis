from typing import Literal
from _typeshed import Incomplete

from __future__ import annotations
import json
import os
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

PASS: Literal['PASS'] = "PASS"


def load_story_json(value: Optional[str], default: Incomplete) -> Incomplete: ...


def compute_summary(conn: sqlite3.Connection) -> Dict[str, Any]: ...


def compute_distributions(conn: sqlite3.Connection) -> Dict[str, Any]: ...


def compute_trends(conn: sqlite3.Connection, top_n: int = 8) -> Dict[str, Any]: ...


def quality_breakdown_by_dimension(conn: sqlite3.Connection) -> Dict[str, Any]: ...


def run_analysis(db_path: str, out_dir: str) -> Dict[str, Any]: ...


def main(argv: Optional[List[str]] = None) -> None: ...
