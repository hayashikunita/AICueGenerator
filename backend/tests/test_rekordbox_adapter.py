from app.rekordbox.compat import (
    DEFAULT_MATRIX,
    CompatEntry,
    CompatMatrix,
    schema_fingerprint,
)
from app.rekordbox.process import is_rekordbox_running


def test_schema_fingerprint_is_order_independent():
    a = {"track": ["id", "name"], "cue": ["id", "in"]}
    b = {"cue": ["in", "id"], "track": ["name", "id"]}
    assert schema_fingerprint(a) == schema_fingerprint(b)
    assert schema_fingerprint(a).startswith("sha256:")


def test_schema_fingerprint_changes_with_columns():
    base = {"track": ["id", "name"]}
    changed = {"track": ["id", "name", "bpm"]}
    assert schema_fingerprint(base) != schema_fingerprint(changed)


def test_default_matrix_is_readonly():
    fp = schema_fingerprint({"track": ["id"]})
    assert DEFAULT_MATRIX.is_supported(fp) is False
    assert DEFAULT_MATRIX.is_writable_format(fp, "WAV") is False


def test_matrix_write_allowed_only_for_listed_format():
    fp = schema_fingerprint({"track": ["id"]})
    matrix = CompatMatrix(
        entries=(
            CompatEntry(
                rekordbox_version="6.7.7",
                pyrekordbox_version="0.4.4",
                schema_fingerprint=fp,
                writable_formats=frozenset({"WAV"}),
            ),
        )
    )
    assert matrix.is_supported(fp) is True
    assert matrix.is_writable_format(fp, "WAV") is True
    assert matrix.is_writable_format(fp, "MP3_VBR") is False


def test_is_rekordbox_running_with_injected_names():
    assert is_rekordbox_running(["explorer.exe", "rekordbox.exe"]) is True
    assert is_rekordbox_running(["Code.exe", "python.exe"]) is False
    assert is_rekordbox_running([]) is False
