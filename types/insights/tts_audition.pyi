from typing import Literal

from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from typing import Optional

MAX_AUDITION_CHARS: Literal[1800] = 1800
DEFAULT_WPM: Literal[155] = 155


def detect_engine() -> Optional[str]: ...


def synthesize(text: str, max_chars: int = ...) -> Optional[bytes]: ...


def engine_status() -> dict: ...
