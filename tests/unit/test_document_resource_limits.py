import sys
import tempfile

import pytest

from tutor_api.services.document_extract import DocumentParseError
from tutor_api.services.document_subprocess import run_bounded


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object 实测")
def test_memory_allocation_above_job_limit_fails():
    with tempfile.TemporaryFile() as output, pytest.raises(DocumentParseError):
        run_bounded(
            [sys.executable, "-c", "import time;time.sleep(.5);x=bytearray(128*1024*1024)"],
            timeout=5,
            output=output,
            max_memory_bytes=64 * 1024 * 1024,
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object 实测")
def test_cpu_bound_process_is_terminated_by_job_quota():
    with tempfile.TemporaryFile() as output, pytest.raises(DocumentParseError) as error:
        run_bounded(
            [sys.executable, "-c", "import time;time.sleep(.5)\nwhile True: pass"],
            # 用户态CPU配额不等于墙钟时间；并行集成测试下给调度留余量。
            timeout=30,
            output=output,
            max_cpu_seconds=1,
        )
    assert error.value.code != "parse_timeout"
