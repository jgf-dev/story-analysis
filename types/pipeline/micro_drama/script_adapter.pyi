from _typeshed import Incomplete

import re
from typing import Dict, Any, List, Optional
from pipeline.micro_drama.models import MicroDramaScript, DialogueLine

EXPLICIT_TERMS: set[str]
SENSORY_SUBSTITUTIONS: list[tuple[str, str]]


class ScriptAdapter:
    def __init__(self) -> Incomplete: ...

    def check_compliance(self, text: str) -> bool: ...

    def sanitize_for_social(self, text: str) -> str: ...

    def adapt_story(self, story_data: Dict[str, Any]) -> MicroDramaScript: ...
