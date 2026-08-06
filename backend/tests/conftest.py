from __future__ import annotations

import os
import tempfile

# テストは本番/ユーザーの実データを触らないよう、一時ディレクトリを使う。
os.environ.setdefault("AICUE_DATA_DIR", tempfile.mkdtemp(prefix="aicue-test-"))
os.environ.setdefault("AICUE_OPEN_BROWSER", "false")
