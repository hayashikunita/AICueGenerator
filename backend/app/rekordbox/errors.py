from __future__ import annotations

from ..domain.enums import ErrorCode


class AdapterError(Exception):
    """rekordbox アダプター層のエラー。機械判定用 code と利用者向け message を持つ。"""

    def __init__(self, code: ErrorCode, message: str, *, retriable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = retriable

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code.value, "message": self.message, "retriable": self.retriable}
