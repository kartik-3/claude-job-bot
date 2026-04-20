from pathlib import Path


class BaseApplier:
    """Shared Playwright session, field detection, and screenshot helpers."""

    def screenshot(self, page: object, name: str) -> Path:
        # Phase 4
        raise NotImplementedError

    def detect_fields(self, page: object) -> list[dict]:
        # Phase 4 — returns list of {label, input_type, required, selector}
        raise NotImplementedError
