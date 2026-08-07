import json
import os
from typing import Any, List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings

load_dotenv()


class DatabaseConfig(BaseModel):
    username: str
    password: str
    host: str
    port: int
    db_name: str
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_timeout: int


class JWTConfig(BaseModel):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    issuer: str = "proposal-ai"


class AWSConfig(BaseModel):
    access_key_id: str
    secret_access_key: str
    region: str
    bucket_name: str


class PineconeConfig(BaseModel):
    api_key: str
    index_name: str
    dimension: int = 1024  # BGE-M3 embedding size
    metric: str = "cosine"
    cloud: str = "aws"
    region: str = "us-east-1"


class GroqConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"

    # The account's tokens-per-minute allowance, and the reason generation has
    # to think about tokens at all. It is NOT only a rate: Groq rejects any
    # *single* request whose prompt plus reserved completion exceeds it,
    # outright, with 413 "Request too large ... on tokens per minute (TPM)".
    # So it doubles as a hard per-request ceiling, and waiting does not fix a
    # 413 the way it fixes a 429 — the request itself has to be smaller.
    #
    # 8000 is the on-demand/free tier, confirmed at runtime from the
    # x-ratelimit-limit-tokens response header. The header is authoritative and
    # overwrites this at runtime (see generation/rate_limit.py); this value only
    # has to be right for the very first request of the process, before any
    # header has been seen.
    tokens_per_minute: int = 8000

    # Fraction of `tokens_per_minute` a single request may plan to occupy. The
    # gap absorbs the difference between our local tiktoken estimate and Groq's
    # own tokenizer — a request estimated at exactly the limit lands on the
    # wrong side of it and 413s.
    request_budget_ratio: float = 0.85


class GenerationConfig(BaseModel):
    """Knobs for the proposal-generation pipeline (generation/graph.py)."""

    # Maximum section drafts in flight at once. Defaults to 1, which reproduces
    # the original strictly-sequential behaviour.
    #
    # Raising this does not make free-tier generation faster: an 8000 TPM cap
    # is a token *rate* limit, so a ~72k-token 10-page run takes ~9 minutes
    # whatever the concurrency — the cap only decides whether you hit the limit
    # in bursts. It is also unsafe above 1 there: a single large section can
    # request ~8000 tokens on its own, so two at once earns a 413 rather than a
    # retryable 429. Raise it on a tier whose TPM can actually absorb the
    # parallelism.
    #
    # Overridable per-process with the GENERATION_CONCURRENCY env var so the
    # value can be changed without editing the CONFIG blob.
    concurrency: int = 1

    # Reasoning effort for drafting calls. `gpt-oss` is a reasoning model: it
    # emits reasoning on a separate `reasoning` delta that nothing streams to
    # the client, while those tokens are still billed against the same
    # max_completion_tokens allowance as the visible draft.
    #
    # This is a correctness setting, not a quality/latency trade-off. Measured
    # on one section at a 300-token cap: at the model default, reasoning
    # consumed all 300 tokens and the section came back COMPLETELY EMPTY; at
    # "low" it spent 25 on reasoning and wrote 204 words for the same billed
    # cost. Drafting is a well-specified writing task — the outline, word
    # budget and context are all supplied — so there is little for deeper
    # reasoning to contribute. Do not raise this without also raising the
    # per-section token cap.
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = "low"

    # Attempts per section when Groq returns 429. Retries wait exactly as long
    # as the Retry-After header asks, so this is an attempt count, not a
    # backoff schedule.
    max_rate_limit_retries: int = 4

    # Throttle a section before it starts if the remaining-token headroom
    # reported by the last response is below this fraction of what the section
    # is estimated to need. Below it, the runner waits for the bucket to refill
    # instead of firing a request that would 429.
    tpm_headroom_ratio: float = 1.0

    @property
    def resolved_concurrency(self) -> int:
        """`concurrency`, with the GENERATION_CONCURRENCY env var taking
        precedence. Invalid or non-positive values fall back to the config
        value rather than failing generation at request time."""

        raw = os.environ.get("GENERATION_CONCURRENCY")
        if raw:
            try:
                override = int(raw)
            except ValueError:
                return max(self.concurrency, 1)
            if override > 0:
                return override
        return max(self.concurrency, 1)


class HFInferenceConfig(BaseModel):
    api_token: str
    embedding_model: str
    hf_base_api_url: str

    @property
    def embedding_api_url(self) -> str:

        return f"{self.hf_base_api_url.rstrip('/')}/{self.embedding_model}/pipeline/feature-extraction"


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0


class SMTPConfig(BaseModel):
    host: str = "smtp.gmail.com"
    port: int = 587
    # Only used by the "smtp" provider — an HTTPS-API provider authenticates
    # with `api_key` instead, so a provider-only deployment can omit these
    # rather than carrying dummy values just to satisfy validation.
    username: Optional[str] = None
    password: Optional[str] = None
    from_email: str
    use_tls: bool = True

    # How mail actually leaves the process.
    #
    #   "smtp"  – classic smtplib over port 587. Works locally, but many hosts
    #             (Render among them) block outbound SMTP entirely; there the
    #             connect fails immediately with
    #             "OSError: [Errno 101] Network is unreachable".
    #   others  – the provider's HTTPS REST API, which goes out over 443 and is
    #             therefore not blocked. Set `api_key` when using one of these.
    #
    # `from_email` is reused as the sender for every provider. For a real
    # provider the sending domain usually has to be verified with them first.
    provider: Literal["smtp", "resend", "brevo", "sendgrid"] = "smtp"
    api_key: Optional[str] = None
    from_name: Optional[str] = None

    @model_validator(mode="after")
    def check_credentials_present(self) -> "SMTPConfig":
        if self.provider == "smtp":
            missing = [name for name in ("username", "password") if not getattr(self, name)]
            if missing:
                raise ValueError(
                    f"smtp.{' and smtp.'.join(missing)} "
                    f"{'is' if len(missing) == 1 else 'are'} required when smtp.provider is 'smtp'"
                )
        elif not self.api_key:
            raise ValueError(f"smtp.api_key is required when smtp.provider is '{self.provider}'")
        return self


class AppConfig(BaseSettings):
    database: DatabaseConfig
    jwt: JWTConfig
    aws: AWSConfig
    pinecone: PineconeConfig
    groq: GroqConfig
    hf_inference: HFInferenceConfig
    redis: RedisConfig = RedisConfig()
    generation: GenerationConfig = GenerationConfig()
    smtp: SMTPConfig
    debug: bool = False
    allowed_origins: List[str] = Field(default_factory=list)

    # Public URL of the web app that outbound email links to — the target of
    # the team-invite "Log in" button. Point it straight at the frontend's
    # sign-in page (e.g. "https://<app>/auth/login"); it is used verbatim, not
    # joined with a path, so a frontend that moves its login route only needs
    # this value changed.
    #
    # Optional so a CONFIG without it still validates, but the default is only
    # right for local dev: leave it unset in a deployed environment and
    # invitees get a link pointing at their own machine.
    base_url: str = "http://localhost:3000/auth/login"

    @model_validator(mode="before")
    @classmethod
    def load_from_config_env(cls, data: Any) -> Any:
        if not data or (isinstance(data, dict) and not data):
            raw_config = os.environ.get("CONFIG")
            if not raw_config:
                raise RuntimeError(
                    """CONFIG environment variable is required 
                    and must be a valid JSON string."""
                )
            try:
                data = json.loads(raw_config)
            except Exception as e:
                raise RuntimeError(f"Failed to parse CONFIG env variable as JSON: {e}")
        return data

    class Config:
        env_file = None
        arbitrary_types_allowed = True


config = AppConfig()
