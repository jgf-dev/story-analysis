from _typeshed import Incomplete

from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from pipeline.embeddings import VectorIndex
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.profiler import StoryProfiler
from pipeline.schemas import RawStory
from pipeline.tts_prioritizer import TTSPrioritizer


def load_raw_stories(input_path: str, limit: int | None = None) -> list[RawStory]: ...


def main() -> Incomplete: ...
