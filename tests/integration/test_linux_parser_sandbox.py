import base64
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from support.documents import docx_document, text_pdf
from tutor_api.services.document_extract import ParseLimits
from tutor_api.services.document_sandbox import linux_parser_command, systemd_scope_command


@pytest.fixture
def sandbox():
    path = os.environ.get("TUTOR_LINUX_SANDBOX_CONFIG")
    if not path:
        pytest.skip("需要显式Linux/WSL隔离配置")
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    command = linux_parser_command(
        bwrap=config["bwrap"],
        runtime=config["runtime"],
        package=config["package"],
        temp_bytes=48 * 1024 * 1024,
    )
    prefix = ["wsl.exe", "-d", config["distribution"], "--"] if sys.platform == "win32" else []
    return config, prefix, command


@pytest.mark.parametrize(
    "kind,data,expected",
    [
        ("pdf", text_pdf("Self authored sandbox PDF"), "Self authored sandbox PDF"),
        (
            "docx",
            docx_document("<w:p><w:r><w:t>Self authored sandbox DOCX</w:t></w:r></w:p>"),
            "Self authored sandbox DOCX",
        ),
    ],
)
def test_real_documents_parse_without_network(sandbox, kind, data, expected):
    _, prefix, command = sandbox
    request = {
        "operation": "extract",
        "kind": kind,
        "content": base64.b64encode(data).decode(),
        "limits": asdict(ParseLimits()),
    }
    result = subprocess.run(
        prefix + command, input=json.dumps(request).encode(), capture_output=True, timeout=30
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert expected in json.loads(result.stdout)["pages"][0]["text"]


@pytest.mark.parametrize("doc_conversion", [False, True])
def test_host_files_environment_and_network_are_not_available(sandbox, doc_conversion):
    config, prefix, command = sandbox
    if doc_conversion:
        if not config.get("doc_converter"):
            pytest.skip("需要显式Linux DOC转换器配置")
        command = linux_parser_command(
            bwrap=config["bwrap"],
            runtime=config["runtime"],
            package=config["package"],
            temp_bytes=48 * 1024 * 1024,
            doc_conversion=True,
        )
    sentinel = config["host_sentinel"]
    code = (
        "import os,socket,sys;from pathlib import Path;"
        f"assert not Path({sentinel!r}).exists();"
        "assert os.getenv('TUTOR_SANDBOX_SECRET') is None;"
        "s=socket.socket();s.settimeout(1);assert s.connect_ex(('127.0.0.1',int(sys.argv[1]))) != 0;"
        "assert not Path('/mnt').exists();assert not Path('/home').exists();"
        "assert not Path('/etc/passwd').exists();"
    )
    if doc_conversion:
        code += (
            "assert Path('/etc/libreoffice/registry').is_dir();"
            "mounts=[line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()];"
            "assert any(m[4]=='/etc/libreoffice' and 'ro' in m[5].split(',') for m in mounts);"
        )
    target = command[:-3] + ["/runtime/bin/python", "-c", code + "print('isolated')"]
    # Prove this host listener is reachable before checking the private namespace.
    script = f"""
import os,socket,subprocess
from pathlib import Path
assert Path({sentinel!r}).read_text()=='host-only-test'
with socket.socket() as listener:
    listener.bind(('127.0.0.1',0))
    listener.listen()
    port=listener.getsockname()[1]
    with socket.create_connection(('127.0.0.1',port),timeout=1):
        pass
    result=subprocess.run({target!r}+[str(port)],
        env={{**os.environ,'TUTOR_SANDBOX_SECRET':'test-only-secret'}},
        capture_output=True,timeout=10)
    assert result.returncode==0, result.stderr.decode(errors='replace')
    assert result.stdout.strip()==b'isolated'
print('isolated')
"""
    result = subprocess.run(
        prefix + [config["runtime"] + "/bin/python", "-"],
        input=script.encode(),
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"isolated"


def test_timeout_kills_sandbox_descendants(sandbox):
    config, prefix, command = sandbox
    child = "import time;time.sleep(1);print('survived',flush=True)"
    parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(20)"
    target = command[:-3] + ["/runtime/bin/python", "-c", parent]
    script = f"""
import sys,tempfile,time
sys.path.insert(0,{str(Path(config["package"]).parent).replace(chr(92), "/")!r})
from tutor_api.services.document_subprocess import run_bounded
from tutor_api.services.document_extract import DocumentParseError
with tempfile.TemporaryFile() as output:
    try:
        run_bounded({target!r},timeout=.3,output=output)
        raise AssertionError('timeout expected')
    except DocumentParseError as error:
        assert error.code == 'parse_timeout'
    time.sleep(1.5)
    output.seek(0)
    assert output.read() == b'', 'descendant survived sandbox timeout'
print('terminated')
"""
    result = subprocess.run(
        prefix + [config["runtime"] + "/bin/python", "-"],
        input=script.encode(),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"terminated"


@pytest.mark.parametrize("cgroup", [False, True])
def test_configured_backend_enforces_isolation_and_missing_tool_fails_closed(sandbox, cgroup):
    config, prefix, _ = sandbox
    data = base64.b64encode(text_pdf("Self authored configured parser")).decode()
    package_parent = str(Path(config["package"]).parent).replace(chr(92), "/")
    script = f"""
import sys,base64
from pathlib import Path
sys.path.insert(0,{package_parent!r})
from tutor_api.settings import Settings
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.document_extract import DocumentParseError
settings=Settings(import_isolation_mode='linux_bwrap',import_linux_bwrap=Path({config["bwrap"]!r}),import_linux_runtime=Path({config["runtime"]!r}),import_memory_limit_bytes=2*1024*1024*1024,import_cpu_limit_seconds=20)
settings.import_linux_cgroup={cgroup!r}
result=parse_isolated(base64.b64decode({data!r}),'pdf',settings)
assert 'Self authored configured parser' in result['pages'][0]['text']
settings.import_linux_bwrap=Path('/unavailable-isolation-tool')
try:
    parse_isolated(base64.b64decode({data!r}),'pdf',settings)
    raise AssertionError('must not fall back')
except DocumentParseError:
    pass
print('configured and failed closed')
"""
    result = subprocess.run(
        prefix + [config["runtime"] + "/bin/python", "-"],
        input=script.encode(),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"configured and failed closed"


@pytest.mark.parametrize("cgroup", [False, True])
def test_real_binary_doc_converts_inside_sandbox(sandbox, cgroup):
    config, prefix, _ = sandbox
    converter = config.get("doc_converter")
    if not converter:
        pytest.skip("需要显式Linux DOC转换器配置")
    # Only this fixed self-authored RTF is converted on the host to create a real DOC.
    # The application then converts that DOC inside its actual sandbox and quotas.
    rtf = base64.b64encode(
        b"{\\rtf1\\ansi\\uc1 \\u33258?\\u32534? Self authored sandbox DOC. Solve x+1=2.}"
    ).decode()
    package_parent = str(Path(config["package"]).parent).replace(chr(92), "/")
    script = f"""
import base64,os,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,{package_parent!r})
from tutor_api.settings import Settings
from tutor_api.services.document_parser_process import parse_isolated
from tutor_api.services.document_extract import DocumentParseError
with tempfile.TemporaryDirectory(prefix='tutor-doc-fixture-') as directory:
    root=Path(directory)
    source=root/'sample.rtf'
    source.write_bytes(base64.b64decode({rtf!r}))
    generated=subprocess.run([
        {converter!r},'-env:UserInstallation='+(root/'profile').as_uri(),
        '--headless','--nologo','--nodefault','--norestore',
        '--convert-to','doc:MS Word 97','--outdir',str(root),str(source)
    ],env={{'HOME':str(root),'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}},
       capture_output=True,timeout=20)
    assert generated.returncode==0, generated.stderr.decode(errors='replace')
    data=(root/'sample.doc').read_bytes()
    assert data.startswith(bytes.fromhex('D0CF11E0A1B11AE1'))
settings=Settings(import_isolation_mode='linux_bwrap',
    import_linux_bwrap=Path({config["bwrap"]!r}),
    import_linux_runtime=Path({config["runtime"]!r}),
    import_doc_converter=Path({converter!r}),
    import_memory_limit_bytes=2*1024*1024*1024,import_cpu_limit_seconds=20,
    import_linux_cgroup={cgroup!r})
result=parse_isolated(data,'doc',settings)
assert 'Self authored sandbox DOC' in result['pages'][0]['text']
assert '\u81ea\u7f16' in result['pages'][0]['text']
assert any('DOC' in warning for warning in result['pages'][0]['warnings'])
settings.import_doc_converter=Path('/unavailable-doc-converter')
try:
    parse_isolated(data,'doc',settings)
    raise AssertionError('missing converter must not fall back')
except DocumentParseError as error:
    assert error.code=='converter_unavailable'
print('binary DOC converted inside sandbox; missing converter failed closed')
"""
    result = subprocess.run(
        prefix + [config["runtime"] + "/bin/python", "-"],
        input=script.encode(),
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert (
        result.stdout.strip()
        == b"binary DOC converted inside sandbox; missing converter failed closed"
    )


def test_cgroup_limits_process_tree_tasks(sandbox):
    _, prefix, command = sandbox
    code = """
import subprocess,sys
children=[]
limited=False
try:
    for _ in range(32):
        try: children.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)']))
        except OSError: limited=True;break
    assert limited, 'process quota was not enforced'
finally:
    for child in children: child.terminate()
    for child in children: child.wait()
print('tasks limited')
"""
    scoped = systemd_scope_command(
        command[:-3] + ["/runtime/bin/python", "-c", code],
        memory_bytes=512 * 1024 * 1024,
        tasks=8,
        cpu_percent=100,
    )
    result = subprocess.run(
        prefix + ["/usr/bin/env", "XDG_RUNTIME_DIR=/run/user/1000", *scoped],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"tasks limited"


def test_scope_kernel_controls_match_requested_limits(sandbox):
    config, prefix, command = sandbox
    scoped = systemd_scope_command(
        command[:-3]
        + ["/runtime/bin/python", "-c", "import sys;print('ready',flush=True);sys.stdin.read()"],
        memory_bytes=512 * 1024 * 1024,
        tasks=8,
        cpu_percent=100,
    )
    unit = next(arg.split("=", 1)[1] for arg in scoped if arg.startswith("--unit="))
    script = f"""
import os,subprocess
from pathlib import Path
env={{**os.environ,'XDG_RUNTIME_DIR':f'/run/user/{{os.getuid()}}'}}
process=subprocess.Popen({scoped!r},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
try:
    assert process.stdout.readline().strip()==b'ready'
    group=subprocess.check_output(['systemctl','--user','show',{unit!r},'--property=ControlGroup','--value'],env=env,text=True).strip()
    root=Path('/sys/fs/cgroup')/group.lstrip('/')
    assert (root/'memory.max').read_text().strip()=='536870912'
    assert (root/'memory.swap.max').read_text().strip()=='0'
    assert (root/'pids.max').read_text().strip()=='8'
    quota,period=(root/'cpu.max').read_text().split()
    assert quota!='max' and int(quota)==int(period)
finally:
    process.stdin.close()
    process.wait(timeout=5)
assert process.returncode==0
print('kernel limits verified')
"""
    result = subprocess.run(
        prefix + ["/usr/bin/python3", "-"], input=script.encode(), capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"kernel limits verified"
