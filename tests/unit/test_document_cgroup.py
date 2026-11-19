import pytest

from tutor_api.services.document_sandbox import systemd_scope_command


def test_scope_applies_group_limits_without_shell_or_persistent_service():
    command = systemd_scope_command(
        ["/opt/bwrap", "--unshare-net"], memory_bytes=512 * 1024 * 1024, tasks=16, cpu_percent=100
    )
    assert command[:4] == ["/usr/bin/systemd-run", "--user", "--scope", "--quiet"]
    assert "--collect" in command
    assert "--property=MemoryMax=536870912" in command
    assert "--property=TasksMax=16" in command
    assert "--property=CPUQuota=100%" in command
    assert command[-2:] == ["/opt/bwrap", "--unshare-net"]


@pytest.mark.parametrize("memory,tasks,cpu", [(0, 16, 100), (1024, 0, 100), (1024, 16, 0)])
def test_invalid_group_limits_fail_before_launch(memory, tasks, cpu):
    with pytest.raises(ValueError):
        systemd_scope_command(["/opt/bwrap"], memory_bytes=memory, tasks=tasks, cpu_percent=cpu)
