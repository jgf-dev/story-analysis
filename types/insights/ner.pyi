from typing import Literal

from __future__ import annotations
import json
import os
import re
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

SETTING_PATTERNS: dict[str, str]
CHARACTER_PATTERNS: dict[str, str]
DYNAMIC_PATTERNS: dict[str, str]
CATEGORY_ALIASES: dict[str, str]
ENTITY_TYPES: tuple[Literal['setting'], Literal['character'], Literal['dynamic']]


def extract_entities(title: str, preview: str, category: str = "") -> Dict[str, List[str]]: ...


def build_entities(db_path: str, batch_size: int = 5000) -> int: ...


SCOPE_JOIN: Literal['JOIN stories s ON s.id = m.story_id AND s.is_canonical=1 AND s.safety_verdict=\'PASS\''] = ("JOIN stories s ON s.id = m.story_id AND s.is_canonical=1 "
              "AND s.safety_verdict='PASS'")


def facet_counts(db_path: str, etype: str, filters: Optional[Dict[str, List[str]]] = None, limit: int = 40) -> List[Tuple[str, int]]: ...


def combo_search(db_path: str, filters: Dict[str, List[str]], extra_where: str = "", args: tuple = (), limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]: ...


def combo_count(db_path: str, filters: Dict[str, List[str]], extra_where: str = "", args: tuple = ()) -> int: ...


def main(argv: Optional[List[str]] = None) -> None: ...
