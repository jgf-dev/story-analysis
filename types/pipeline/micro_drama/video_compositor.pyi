from typing import Literal
from _typeshed import Incomplete

import os
import subprocess
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from pipeline.micro_drama.models import MicroDramaScript

DEFAULT_HANDLES: dict[str, str]
FONT_BOLD: Literal['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR: Literal['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class VideoCompositor:
    height: int
    width: int
    work_dir: str

    def __init__(self, work_dir: str = "/tmp/micro_drama_video") -> Incomplete: ...

    def generate_base_overlay(self, script: MicroDramaScript, output_path: str, handles: Optional[Dict[str, str]] = None) -> str: ...

    def generate_outro_card(self, script: MicroDramaScript, output_path: str, handles: Optional[Dict[str, str]] = None) -> str: ...

    def compose_video(self, script: MicroDramaScript, audio_path: str, duration_sec: float, subtitle_path: str, output_path: str, dialogue_duration_sec: Optional[float] = None, handles: Optional[Dict[str, str]] = None) -> str: ...
