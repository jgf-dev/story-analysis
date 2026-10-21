from typing import ClassVar, Literal
from _typeshed import Incomplete

import time
from dataclasses import dataclass, field
from unstructured_transform_client import TransformClient

MAX_ATTEMPTS: Literal[10] = 10
MAX_WAIT_SECONDS: Literal[60] = 60
TIMEOUT_SECONDS: Literal[300] = 300


@dataclass(frozen=True)
class Limits:
    MAX_FILE_SIZE: int
    SUPPORTED_FILE_TYPES: set[str]
    MAX_SCHEMA_SIZE: int
    MAX_PROMPT_SIZE: int

    def __init__(self, MAX_FILE_SIZE: int = ..., SUPPORTED_FILE_TYPES: set[str] = ..., MAX_SCHEMA_SIZE: int = ..., MAX_PROMPT_SIZE: int = ...) -> None: ...


@dataclass(frozen=False)
class VariableLimits:
    RESULT_SIZE_LIMIT: int
    RATE_LIMIT: int = 1000
    CONCURRENT_JOBS_LIMIT: int = 10

    def size_limit_hit(self) -> bool: ...

    def rate_limit_hit(self) -> bool: ...

    def concurrent_jobs_limit_hit(self) -> bool: ...

    def try_larger_result(self) -> bool: ...

    def try_larger_rate(self) -> bool: ...

    def try_larger_concurrent_jobs(self) -> bool: ...

    def __init__(self, RESULT_SIZE_LIMIT: int = ..., RATE_LIMIT: int = ..., CONCURRENT_JOBS_LIMIT: int = ...) -> None: ...


@dataclass(frozen=True)
class JobStatus:
    QUEUED: ClassVar[Literal['queued']] = "queued"
    PROCESSING: ClassVar[Literal['processing']] = "processing"
    COMPLETED: ClassVar[Literal['completed']] = "completed"
    COMPLETED_WITH_WARNINGS: ClassVar[Literal['completed_with_warnings']] = "completed_with_warnings"
    FAILED: ClassVar[Literal['failed']] = "failed"
    CANCELED: ClassVar[Literal['canceled']] = "canceled"

    def __init__(self) -> None: ...


@dataclass(frozen=True)
class JobOperation:
    PARSE: ClassVar[Literal['parse']] = "parse"
    EXTRACT: ClassVar[Literal['extract']] = "extract"
    CLASSIFY: ClassVar[Literal['classify']] = "classify"
    SUMMARIZE: ClassVar[Literal['summarize']] = "summarize"
    TRANSLATE: ClassVar[Literal['translate']] = "translate"
    CONVERT: ClassVar[Literal['convert']] = "convert"
    GENERATE: ClassVar[Literal['generate']] = "generate"

    def __init__(self) -> None: ...


@dataclass(frozen=True)
class FailureReason:
    TIMEOUT: ClassVar[Literal['timeout']] = "timeout"
    MISSING_INPUT: ClassVar[Literal['missing_input']] = "missing_input"
    INVALID_INPUT: ClassVar[Literal['invalid_input']] = "invalid_input"
    MALLFORMED_SCHEMA: ClassVar[Literal['malformed_schema']] = "malformed_schema"
    INVALID_SCHEMA: ClassVar[Literal['invalid_schema']] = "invalid_schema"
    SCHEMA_TOO_LARGE: ClassVar[Literal['schema_too_large']] = "schema_too_large"
    FILE_TOO_LARGE: ClassVar[Literal['file_too_large']] = "file_too_large"
    UNSUPPORTED_FILE_TYPE: ClassVar[Literal['unsupported_file_type']] = "unsupported_file_type"
    INVALID_OUTPUT_FORMAT: ClassVar[Literal['invalid_output_format']] = "invalid_output_format"
    OUTPUT_OPTION_UNAVAILABLE: ClassVar[Literal['output_option_unavailable']] = "output_option_unavailable"
    UNAUTHORIZED_401: ClassVar[Literal['unauthorized']] = "unauthorized"
    FORBIDDEN_403: ClassVar[Literal['forbidden']] = "forbidden"
    AUTHORIZATION_UNAVAILABLE_503: ClassVar[Literal['authorization_unavailable']] = "authorization_unavailable"
    NOT_FOUND_404: ClassVar[Literal['not_found']] = "not_found"
    PARSE_NOT_COMPLETE: ClassVar[Literal['parse_not_complete']] = "parse_not_complete"
    PARSE_EXPIRED: ClassVar[Literal['parse_expired']] = "parse_expired"
    INPUT_URL_EXPIRED_502: ClassVar[Literal['input_url_expired']] = "input_url_expired"
    RESULT_EXPIRED_410: ClassVar[Literal['result_expired']] = "result_expired"
    QUOTA_EXCEEDED: ClassVar[Literal['quota_exceeded']] = "quota_exceeded"
    RATE_LIMITED: ClassVar[Literal['rate_limited']] = "rate_limited"
    PROFILE_UNAVAILABLE_502: ClassVar[Literal['profile_unavailable']] = "profile_unavailable"
    PROFILE_TEMPORARILY_UNAVAILABLE_503: ClassVar[Literal['profile_temporarily_unavailable']] = "profile_temporarily_unavailable"
    COULD_NOT_PARSE: ClassVar[Literal['could_not_parse']] = "could_not_parse"
    PARSE_JOB_FAILED_500: ClassVar[Literal['parse_failed']] = "parse_failed"
    JOB_NOT_TERMINAL: ClassVar[Literal['job_not_terminal']] = "job_not_terminal"
    METHOD_NOT_ALLOWED: ClassVar[Literal['method_not_allowed']] = "method_not_allowed"
    INTERNAL_ERROR_500: ClassVar[Literal['internal_error']] = "internal_error"
    HTTP_502: ClassVar[Literal[502]] = 502

    def __init__(self) -> None: ...


def create_client() -> Incomplete: ...


def parse_document(file_path: str) -> Incomplete: ...


def parse_document_with_polling(file_path: str) -> Incomplete: ...


def extract_data(job_id: str, schema: dict | None = None, timeout_seconds: int = 300, wait_seconds: int = 2) -> Incomplete: ...


def get_jobs(status: str | None = None, operation: str | None = None, limit: int | None = None) -> Incomplete: ...


def get_job_pages(status: str | None = None, operation: str | None = None, limit: int | None = None) -> Incomplete: ...


def completed_result(client: Incomplete, response: Incomplete) -> Incomplete: ...


def parse_and_extract(file_path: str, schema: dict | None = None) -> Incomplete: ...
