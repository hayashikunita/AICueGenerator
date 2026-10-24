from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..domain.enums import ErrorCode
from .errors import AdapterError


@contextmanager
def open_database(
    path: str | Path,
    *,
    key: str = "",
    unlock: bool = True,
) -> Iterator[Any]:
    """rekordbox master.db を開くコンテキストマネージャ。

    pyrekordbox の例外を AdapterError (ErrorCode 付き) に翻訳する。
    クローズは finally で必ず行う。
    """
    try:
        from pyrekordbox import Rekordbox6Database
    except ImportError as exc:  # pyrekordbox 未導入
        raise AdapterError(
            ErrorCode.WRITE_DISABLED,
            f"pyrekordbox が導入されていません: {exc}",
            retriable=False,
        ) from exc

    try:
        db = Rekordbox6Database(path=str(path), key=key, unlock=unlock)
    except ImportError as exc:  # sqlcipher3 不在で復号不可
        raise AdapterError(
            ErrorCode.DB_KEY_UNAVAILABLE,
            f"SQLCipher で復号できません (sqlcipher3 不在の可能性): {exc}",
            retriable=False,
        ) from exc
    except FileNotFoundError as exc:
        raise AdapterError(
            ErrorCode.UNKNOWN_SCHEMA,
            f"master.db が見つかりません: {exc}",
            retriable=False,
        ) from exc
    except ValueError as exc:  # 鍵不正など
        raise AdapterError(
            ErrorCode.DB_KEY_UNAVAILABLE,
            f"DB の鍵が無効か復号に失敗しました: {exc}",
            retriable=False,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 未知の失敗も安全側で翻訳
        raise AdapterError(
            ErrorCode.UNKNOWN_SCHEMA,
            f"DB を開けませんでした: {exc}",
            retriable=False,
        ) from exc

    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - クローズ失敗は無視
            pass


@contextmanager
def open_rekordbox(
    *, path: str | None = None, key: str | None = None
) -> Iterator[Any]:
    """設定または自動検出で rekordbox master.db を読取用に開く。

    path/key が未指定なら pyrekordbox の自動検出に委ねる。例外は AdapterError に翻訳する。
    """
    try:
        from pyrekordbox import Rekordbox6Database
    except ImportError as exc:
        raise AdapterError(
            ErrorCode.WRITE_DISABLED,
            f"pyrekordbox が導入されていません: {exc}",
            retriable=False,
        ) from exc

    kwargs: dict[str, Any] = {"unlock": True}
    if path:
        kwargs["path"] = str(path)
    if key:
        kwargs["key"] = str(key)

    try:
        db = Rekordbox6Database(**kwargs)
    except ImportError as exc:  # sqlcipher3 不在
        raise AdapterError(
            ErrorCode.DB_KEY_UNAVAILABLE,
            f"SQLCipher で復号できません (sqlcipher3 不在の可能性): {exc}",
            retriable=False,
        ) from exc
    except FileNotFoundError as exc:
        raise AdapterError(
            ErrorCode.UNKNOWN_SCHEMA,
            f"master.db が見つかりません: {exc}",
            retriable=False,
        ) from exc
    except ValueError as exc:  # 鍵不正など
        raise AdapterError(
            ErrorCode.DB_KEY_UNAVAILABLE,
            f"DB の鍵が無効か復号に失敗しました: {exc}",
            retriable=False,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 未知の失敗も安全側で翻訳
        raise AdapterError(
            ErrorCode.UNKNOWN_SCHEMA,
            f"DB を開けませんでした: {exc}",
            retriable=False,
        ) from exc

    try:
        # アプリのライブラリ参照は、SQLite 接続でも書き込みを禁止する。
        from sqlalchemy import text
        db.session.execute(text("PRAGMA query_only=ON"))
        yield db
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - クローズ失敗は無視
            pass


def read_schema(db: Any) -> dict[str, list[str]]:
    """実際の DB スキーマ (テーブル -> 列名) を返す。互換指紋の入力に使う。"""
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(db.engine)
    return {
        table: [col["name"] for col in inspector.get_columns(table)]
        for table in inspector.get_table_names()
    }
