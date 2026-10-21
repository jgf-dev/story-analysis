import time
from dataclasses import dataclass, field

from unstructured_transform_client import TransformClient

MAX_ATTEMPTS = 10
MAX_WAIT_SECONDS = 60
TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Limits:
    """Limits for the Transform API."""

    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB
    SUPPORTED_FILE_TYPES: set[str] = field(default_factory=lambda: {"bmp", "docx", "heic", "jpeg", "jpg", "pdf", "png", "pptx", "tiff"})
    MAX_SCHEMA_SIZE: int = 1024 * 1024  # 1 MB
    MAX_PROMPT_SIZE: int = 1024 * 1024  # 1 MB


@dataclass(frozen=False)
class VariableLimits:
    """Undisclosed limits for the Transform API to be treated as unknown."""

    RESULT_SIZE_LIMIT: int = 10 * 1024 * 1024  # 10 MB
    RATE_LIMIT: int = 1000  # 1000 requests per minute
    CONCURRENT_JOBS_LIMIT: int = 10  # 10 concurrent jobs per user

    def size_limit_hit(self) -> bool:
        """Check if the result size exceeds the limit."""
        self.RESULT_SIZE_LIMIT = self.RESULT_SIZE_LIMIT // 2  # Halve the limit for testing purposes

    def rate_limit_hit(self) -> bool:
        """Check if the rate limit has been hit."""
        self.RATE_LIMIT = self.RATE_LIMIT // 2  # Halve the limit for testing purposes

    def concurrent_jobs_limit_hit(self) -> bool:
        """Check if the concurrent jobs limit has been hit."""
        self.CONCURRENT_JOBS_LIMIT = self.CONCURRENT_JOBS_LIMIT - 1  # Halve the limit for testing purposes

    def try_larger_result(self) -> bool:
        """Attempt to increase the result size limit."""
        self.RESULT_SIZE_LIMIT = self.RESULT_SIZE_LIMIT + 1024  # Double the limit for testing purposes

    def try_larger_rate(self) -> bool:
        """Attempt to increase the rate limit."""
        self.RATE_LIMIT = self.RATE_LIMIT + 10  # Double the limit for testing purposes

    def try_larger_concurrent_jobs(self) -> bool:
        """Attempt to increase the concurrent jobs limit."""
        self.CONCURRENT_JOBS_LIMIT = self.CONCURRENT_JOBS_LIMIT + 1  # Double the limit for testing purposes


@dataclass(frozen=True)
class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class JobOperation:
    PARSE = "parse"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"
    TRANSLATE = "translate"
    CONVERT = "convert"
    GENERATE = "generate"


@dataclass(frozen=True)
class FailureReason:
    TIMEOUT = "timeout"
    MISSING_INPUT = "missing_input"
    INVALID_INPUT = "invalid_input"
    MALLFORMED_SCHEMA = "malformed_schema"
    INVALID_SCHEMA = "invalid_schema"
    SCHEMA_TOO_LARGE = "schema_too_large"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    INVALID_OUTPUT_FORMAT = "invalid_output_format"
    OUTPUT_OPTION_UNAVAILABLE = "output_option_unavailable"
    UNAUTHORIZED_401 = "unauthorized"  # / HTTP 401	Check the ID, credential, and expiry; re-upload if needed.
    FORBIDDEN_403 = "forbidden"  # / HTTP 403	Check the ID, credential, and expiry; re-upload if needed.
    AUTHORIZATION_UNAVAILABLE_503 = "authorization_unavailable"
    NOT_FOUND_404 = "not_found"  # / HTTP 404	Check the ID, credential, and expiry; re-upload if needed.
    PARSE_NOT_COMPLETE = "parse_not_complete"  # Wait for a successful Parse before extracting; inspect failed jobs.
    PARSE_EXPIRED = "parse_expired"  # Parse the original document again.
    INPUT_URL_EXPIRED_502 = "input_url_expired"  # / HTTP 502	The input URL expired before the worker fetched the
    # document. Retry the original request.
    RESULT_EXPIRED_410 = "result_expired"  # / HTTP 410	The job metadata remains available, but its stored result is
    # no longer available. Re-run the original request.
    QUOTA_EXCEEDED = "quota_exceeded"  # Check the response message and your account’s available quota before retrying.
    RATE_LIMITED = "rate_limited"  # The API reference lists this reserved code in ErrorCode, but Transform does
    # not currently return this code or provide a Retry-After header for it. If you receive it, do not retry
    # automatically; contact support with the operation, HTTP status, and public error code.
    PROFILE_UNAVAILABLE_502 = "profile_unavailable"  # / HTTP 502	Parse and direct Extract can return this code.
    # Omit the optional profile or use a profile listed in the Parse reference.
    PROFILE_TEMPORARILY_UNAVAILABLE_503 = "profile_temporarily_unavailable"  # / HTTP 503	If the response includes
    # Retry-After, wait for the number of seconds specified by that header, then retry the request.
    # If the header is missing, contact support with the operation, HTTP status, and public error code.
    COULD_NOT_PARSE = "could_not_parse"  # Verify that the file opens, matches a supported file type, is within
    # the size limit, and has readable text or scanned pages. Read the returned message, correct the
    # file or request, then retry.
    PARSE_JOB_FAILED_500 = "parse_failed"  # / HTTP 500	Parse can return this response without creating a job.
    # Retry the original request after checking the file and request. If failures continue, contact support
    # with the operation, HTTP status, and public error code.
    JOB_NOT_TERMINAL = "job_not_terminal"  # Wait for a terminal status before deleting a job.
    METHOD_NOT_ALLOWED = "method_not_allowed"  # Check the HTTP method in the endpoint reference.
    INTERNAL_ERROR_500 = "internal_error"  # / HTTP 500	Upload can return this response without creating a job. Retry
    # the original upload after checking the file and request. If failures continue, contact support with the operation,
    # HTTP status, and public error code.
    HTTP_502 = 502


def create_client():
    """Create a TransformClient instance with specified timeout and retry settings."""
    return TransformClient(timeout_seconds=TIMEOUT_SECONDS, max_attempts=MAX_ATTEMPTS, max_wait_seconds=MAX_WAIT_SECONDS)


def parse_document(file_path: str):
    """Parse a document using the Unstructured Transform API."""
    with create_client() as client:
        job = client.parse.run(input=file_path)
        return job


def parse_document_with_polling(file_path: str):
    """Parse a document using the Unstructured Transform API with polling for completion."""
    with create_client() as client:
        # Submit once and retain the job ID for retrieval.
        accepted = client.parse.run(input=file_path, wait_seconds=0)
        print("Parse job ID:", accepted.id)

        # Poll the same job until processing reaches a final status.
        job = client.jobs.get(accepted.id)
        while job.status in ("queued", "processing"):
            time.sleep(2)
            job = client.jobs.get(accepted.id)

        # Retrieval wraps the parsed document under result.
        if job.status in ("completed", "completed_with_warnings"):
            print(job.result)
        elif job.status == "failed":
            raise RuntimeError(job.error)
        else:
            print("Parse stopped:", job.status)
        return job


def extract_data(job_id: str, schema: dict | None = None, timeout_seconds: int = 300, wait_seconds: int = 2):
    """Query the status of a parse job using the Unstructured Transform API."""

    with create_client() as client:
        parse_id = job_id
        schema = schema or {"type": "object", "properties": {}}
        accepted = client.extract.run(parse_id=parse_id, schema=schema, wait_seconds=0)
        deadline = time.monotonic() + timeout_seconds
        job = client.jobs.get(accepted.id)
        while job.status in ("queued", "processing"):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"extraction {accepted.id} is still {job.status}")
            time.sleep(wait_seconds)
            job = client.jobs.get(accepted.id)
        if job.status in ("completed", "completed_with_warnings"):
            print(job.result.extracted_data)
        elif job.status == "failed":
            raise RuntimeError(job.error)
        else:
            print("Extraction stopped:", job.status)
        return job


def get_jobs(status: str | None = None, operation: str | None = None, limit: int | None = None):
    """Get a list of jobs from the Unstructured Transform API."""
    with create_client() as client:
        for job in client.jobs.iterate(status=status, operation=operation, limit=limit):
            print(job.id, job.status)


def get_job_pages(status: str | None = None, operation: str | None = None, limit: int | None = None):
    """Get a list of jobs from the Unstructured Transform API."""
    with create_client() as client:
        pages = client.jobs.list(status=status, operation=operation, limit=limit)
        print(f"Total pages: {pages.total_count}")


def completed_result(client, response):
    if response.status in ("queued", "processing"):
        job = client.jobs.get(response.id)
        while job.status in ("queued", "processing"):
            time.sleep(2)
            job = client.jobs.get(response.id)
        if job.status not in ("completed", "completed_with_warnings") or job.result is None:
            raise RuntimeError("Job did not complete with a result")
        return job.result
    if response.status not in ("completed", "completed_with_warnings"):
        raise RuntimeError("Request did not complete")
    return response


def parse_and_extract(file_path: str, schema: dict | None = None):
    """Parse a document and extract data using the Unstructured Transform API."""
    with create_client() as client:
        parsed = completed_result(client, client.parse.run(input=file_path))
        extraction = completed_result(client, client.extract.run(parse_id=parsed.id, schema=schema))
        return extraction.extracted_data
