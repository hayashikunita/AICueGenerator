from __future__ import annotations


def sqlcipher_available() -> bool:
    """master.db (SQLCipher) を復号できるか。sqlcipher3 の有無で決まる。

    False の場合、鍵があっても読取・書込ともに不可 (P0 S1 のブロッカー)。
    """
    try:
        from pyrekordbox.db6 import database as _database
    except ImportError:
        return False
    return bool(getattr(_database, "_sqlcipher_available", False))
