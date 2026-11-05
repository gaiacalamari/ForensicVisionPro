import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from fvp.core.tools import locate  # noqa: E402  (cerca in bin/ e poi nel PATH, come il programma)

HAS_EXIFTOOL = locate("exiftool") is not None
HAS_FFMPEG = locate("ffmpeg") is not None and locate("ffprobe") is not None
needs_exiftool = pytest.mark.skipif(not HAS_EXIFTOOL, reason="ExifTool non disponibile")
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg/FFprobe non disponibili")


@pytest.fixture(scope="session")
def dataset(tmp_path_factory) -> Path:
    import make_testdata
    d = tmp_path_factory.mktemp("dataset")
    make_testdata.main(d)
    return d


@pytest.fixture(scope="session")
def manifest(dataset) -> dict:
    return json.loads((dataset / "MANIFEST.json").read_text(encoding="utf-8"))


@pytest.fixture
def case(tmp_path):
    from fvp.cases.store import Case
    c = Case.create(tmp_path / "cases", "T-001", "test", "tester")
    yield c
    c.close()
