"""Dependencies required by study APIs; user identity is resolved per request."""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class StudyServices:
    current_profile: Callable[[], Any]
    study: Any
    exams: Any
    media: Any
    llm: Any
    privacy: Any
    config: Any
    events: Any
