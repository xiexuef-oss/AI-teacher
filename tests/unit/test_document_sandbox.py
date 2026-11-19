import pytest

from tutor_api.services.document_sandbox import linux_parser_command


def test_parser_has_private_network_minimal_mounts_and_clean_environment():
    command = linux_parser_command(
        bwrap="/tools/bwrap",
        runtime="/opt/parser-venv",
        package="/opt/parser-code/tutor_api",
        temp_bytes=1024 * 1024,
    )
    assert "--unshare-net" in command and "--clearenv" in command
    assert "--new-session" in command and "--cap-drop" in command
    assert "--size" in command and "1048576" in command
    assert "/home" not in command and "/mnt" not in command
    assert command[-3:] == ["/runtime/bin/python", "-m", "tutor_api.document_parser"]
    assert not any(
        command[index : index + 3] == ["--ro-bind", "/", "/"] for index in range(len(command))
    )


def test_only_doc_conversion_mounts_readonly_office_registry():
    options = dict(
        bwrap="/tools/bwrap",
        runtime="/opt/parser-venv",
        package="/opt/parser-code/tutor_api",
        temp_bytes=1024 * 1024,
    )
    plain = linux_parser_command(**options)
    doc = linux_parser_command(**options, doc_conversion=True)
    mount = ["--ro-bind", "/etc/libreoffice", "/etc/libreoffice"]
    assert "/etc/libreoffice" not in plain
    assert any(doc[index : index + 3] == mount for index in range(len(doc)))
    assert "/etc" not in doc and "/etc/fonts" not in doc
    assert "--unshare-net" in doc and "--clearenv" in doc
    assert "/home" not in doc and "/mnt" not in doc
    assert doc[-3:] == plain[-3:]


@pytest.mark.parametrize("runtime", ["/", "relative/path", "/opt/../home", "/home"])
def test_unsafe_runtime_mounts_are_rejected(runtime):
    with pytest.raises(ValueError):
        linux_parser_command(
            bwrap="/tools/bwrap", runtime=runtime, package="/opt/tutor_api", temp_bytes=1024
        )
