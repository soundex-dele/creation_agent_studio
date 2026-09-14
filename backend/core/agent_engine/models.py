from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    role: Role
    content: str


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class LLMResponse(BaseModel):
    content: str
    usage: TokenUsage
    model: str
    success: bool = True
    error: str | None = None
    input_request: dict | None = None
    thread_id: str | None = None


class Conversation(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    max_context_messages: int = 20

    def add(self, role: Role, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def trim(self) -> None:
        if len(self.messages) <= self.max_context_messages:
            return
        system_msgs = [m for m in self.messages if m.role == Role.SYSTEM]
        non_system = [m for m in self.messages if m.role != Role.SYSTEM]
        keep = self.max_context_messages - len(system_msgs)
        self.messages = system_msgs + non_system[-keep:]

    def to_api_format(self) -> list[dict]:
        return [{"role": m.role.value, "content": m.content} for m in self.messages]

    def clear(self) -> None:
        self.messages = [m for m in self.messages if m.role == Role.SYSTEM]


class ImageResponse(BaseModel):
    """Image generation result."""
    url: str | None = None
    base64: str | None = None
    revised_prompt: str | None = None
    success: bool = True
    error: str | None = None


class VideoTaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoTask(BaseModel):
    """Video generation task (async)."""
    task_id: str
    status: VideoTaskStatus = VideoTaskStatus.PENDING
    url: str | None = None
    cover_url: str | None = None
    error: str | None = None


class ImageConfig(BaseModel):
    api_key: str = ""
    model: str = "dall-e-3"
    base_url: str = "https://api.openai.com/v1"
    size: str = "1024x1024"
    quality: str = "standard"
    timeout: int = 120
    max_retries: int = 2


class VideoConfig(BaseModel):
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    timeout: int = 300
    poll_interval: float = 5.0
    max_retries: int = 2


class EngineConfig(BaseModel):
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    temperature: float = 0.7
    max_tokens: int = 4096
    max_retries: int = 2
    timeout: int = 60


class JieKouConfig(BaseModel):
    """JieKou AI — single API key for chat / image / video / task-query."""
    api_key: str = ""
    base_url: str = "https://api.highwayapi.ai"
    model: str = "deepseek/deepseek-r1-0528"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120
    max_retries: int = 2
    poll_interval: float = 5.0


class AsyncTask(BaseModel):
    """Async task result returned by the unified task-result endpoint."""
    task_id: str = ""
    status: str = ""
    reason: str | None = None
    progress_percent: int | None = None
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    audio_urls: list[str] = Field(default_factory=list)
    success: bool = True
    error: str | None = None
