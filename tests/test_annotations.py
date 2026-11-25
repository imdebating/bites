"""Runner annotations preserve CLI diagnostics and escape untrusted message text."""
import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import annotations, cli, build  # noqa: E402
from bites_tool.core import BitesError  # noqa: E402


@pytest.mark.parametrize("value", [None, "", "false", "TRUE", "1"])
def test_annotations_disabled_unless_exact_true(monkeypatch, capsys, value):
    if value is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", value)
    annotations.annotate("error", "problem", title="bites build")
    assert capsys.readouterr().out == ""


def test_escaping_and_single_command(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    annotations.annotate("warning", "100%\r\n::error::injected,:", title="bites: a,b%\n")
    captured = capsys.readouterr()
    assert captured.out == "::warning title=bites%3A a%2Cb%25%0A::100%25%0D%0A::error::injected,:\n"
    assert captured.err == ""


def test_literal_escape_sequences_not_decoded():
    assert annotations.escape_data("%0A") == "%250A"


def test_unknown_level_refused():
    with pytest.raises(ValueError):
        annotations.annotate("notice", "problem", title="bites")


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("unexpected", [False, True])
def test_cli_error_keeps_stderr_status_and_exit(monkeypatch, capsys, tmp_path, enabled, unexpected):
    monkeypatch.setenv("GITHUB_ACTIONS", "true" if enabled else "false")
    status = tmp_path / "status.json"
    def fail(a):
        if unexpected:
            raise RuntimeError("bad%\nvalue")
        raise BitesError("bad%\nvalue")
    args = argparse.Namespace(cmd="build", status=str(status), func=fail)
    parser = argparse.ArgumentParser()
    monkeypatch.setattr(parser, "parse_args", lambda argv: args)
    monkeypatch.setattr(cli, "make_parser", lambda: parser)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    msg = ("RuntimeError: " if unexpected else "") + "bad%\nvalue"
    assert captured.err == f"bites build: Error: {msg}\n"
    assert captured.out == (f"::error title=bites build::{annotations.escape_data(msg)}\n" if enabled else "")
    data = json.loads(status.read_text())
    assert data["message"] == msg and data["stage"] == "build" and data["status"] == "error"


@pytest.mark.parametrize("enabled", [False, True])
def test_build_warning_keeps_stderr(monkeypatch, capsys, enabled):
    monkeypatch.setenv("GITHUB_ACTIONS", "true" if enabled else "false")
    monkeypatch.setattr(build, "load_config", lambda *a: {})
    monkeypatch.setattr(build, "collect_overrides", lambda *a: {})
    monkeypatch.setattr(build, "config_warnings", lambda cfg: ["unsafe%\nsetting"])
    # Stop immediately after warning emission; the build algorithm is tested separately.
    with pytest.raises(KeyError):
        build.cmd_build(argparse.Namespace(config="unused", set=[]))
    captured = capsys.readouterr()
    assert "unsafe%\nsetting" in captured.err
    assert "::warning" not in captured.err
    assert captured.out == ("::warning title=bites build::unsafe%25%0Asetting\n" if enabled else "")
