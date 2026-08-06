"""解析コア（decode / beatgrid / features / phrases / structure / scoring）。

純ロジック（features/phrases/structure/scoring/fingerprint）は numpy のみ依存で
合成信号によりテスト可能。decode/beatgrid の実音源処理は soundfile/librosa を
遅延 import する（未導入時は明示的に失敗）。
"""
