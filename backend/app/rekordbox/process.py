from __future__ import annotations

from collections.abc import Iterable

# rekordbox プロセス名の判定に用いる部分一致キーワード。
_REKORDBOX_KEYWORD = "rekordbox"


def _iter_process_names() -> Iterable[str]:
    """稼働中プロセス名を列挙する。psutil が無ければ空を返す。"""
    try:
        import psutil
    except ImportError:
        return ()
    names: list[str] = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
        except Exception:
            name = None
        if name:
            names.append(name)
    return names


def is_rekordbox_running(process_names: Iterable[str] | None = None) -> bool:
    """rekordbox プロセスが稼働中か判定する。テスト時は process_names を注入する。"""
    names = process_names if process_names is not None else _iter_process_names()
    return any(_REKORDBOX_KEYWORD in (n or "").lower() for n in names)
