import http.client
import plistlib
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import scripts.install_login_services as installer
from scripts.run_launchd_bridge import preflight


ROOT = Path(__file__).resolve().parents[1]


def config(home):
    directory = home / ".config"
    directory.mkdir()
    for name, content in (("imcp-bridge.token", "fixture-token"), ("imcp-bridge-tools.json", '{"tools":[]}')):
        target = directory / name
        target.write_text(content)
        target.chmod(0o600)
    return directory


def test_preflight_accepts_private_valid_files(tmp_path):
    config(tmp_path)
    with patch("scripts.run_launchd_bridge.socket.socket") as socket:
        assert len(preflight(tmp_path)) == 2
        socket.return_value.__enter__.return_value.setsockopt.assert_called_once()


def test_preflight_rejects_public_token(tmp_path):
    directory = config(tmp_path)
    (directory / "imcp-bridge.token").chmod(0o644)
    with pytest.raises(ValueError):
        preflight(tmp_path)


def test_preflight_rejects_invalid_allowlist(tmp_path):
    directory = config(tmp_path)
    (directory / "imcp-bridge-tools.json").write_text("invalid")
    with pytest.raises(ValueError):
        preflight(tmp_path)


def test_preflight_rejects_collision(tmp_path):
    config(tmp_path)
    with patch("scripts.run_launchd_bridge.socket.socket") as socket:
        socket.return_value.__enter__.return_value.bind.side_effect = OSError("occupied")
        with pytest.raises(OSError):
            preflight(tmp_path)


def _string_values(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    return []


def test_rendered_templates_are_parseable_and_have_no_template_markers(tmp_path):
    home = tmp_path / "home & fixture"

    rendered = installer._render_templates(home)

    assert set(rendered) == set(installer.LABELS)
    for data in rendered.values():
        plistlib.loads(data)
        assert b"{{" not in data
        assert b"}}" not in data
    bridge = plistlib.loads(rendered[installer.BRIDGE_LABEL])
    assert str(home) in _string_values(bridge)


def _prepare_app(home):
    app = home / "Applications" / "iMCP.app"
    app.mkdir(parents=True)
    return app


def _ready_connection(*_args, **_kwargs):
    connection = Mock()
    connection.getresponse.return_value.status = 401
    return connection


def test_existing_file_drift_refuses_before_any_write_or_bootstrap(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    destination = home / "Library" / "LaunchAgents"
    destination.mkdir(parents=True)
    drifted = destination / f"{installer.LABELS[0]}.plist"
    drifted.write_bytes(b"drifted rendered plist")
    app = _prepare_app(home)
    launchctl = Mock()

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight") as preflight_mock,
        patch.object(installer.subprocess, "run", launchctl),
    ):
        status = installer.main()

    assert status == 1
    assert drifted.read_bytes() == b"drifted rendered plist"
    launchctl.assert_not_called()
    preflight_mock.assert_not_called()
    assert "differs" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["malformed", "different"])
def test_invalid_existing_file_refuses_before_writing_other_target(tmp_path, kind, capsys):
    home = tmp_path / "home"
    home.mkdir()
    destination = home / "Library" / "LaunchAgents"
    destination.mkdir(parents=True)
    rendered = installer._render_templates(home)
    target = destination / f"{installer.LABELS[1]}.plist"
    if kind == "malformed":
        target.write_bytes(b"not a plist")
    else:
        document = plistlib.loads(rendered[installer.LABELS[1]])
        document["Label"] = "com.example.drifted"
        target.write_bytes(plistlib.dumps(document))
    before = target.read_bytes()
    app = _prepare_app(home)
    launchctl = Mock()

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight") as preflight_mock,
        patch.object(installer.subprocess, "run", launchctl),
    ):
        status = installer.main()

    first_target = destination / f"{installer.LABELS[0]}.plist"
    assert status == 1
    assert not first_target.exists()
    assert target.read_bytes() == before
    launchctl.assert_not_called()
    preflight_mock.assert_not_called()
    assert "differs" in capsys.readouterr().err


def test_symlink_existing_target_refuses_before_writing_or_bootstrapping(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    destination = home / "Library" / "LaunchAgents"
    destination.mkdir(parents=True)
    replacement = tmp_path / "replacement.plist"
    replacement.write_bytes(b"target must not be touched")
    target = destination / f"{installer.LABELS[0]}.plist"
    target.symlink_to(replacement)
    app = _prepare_app(home)
    launchctl = Mock()

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight") as preflight_mock,
        patch.object(installer.subprocess, "run", launchctl),
    ):
        status = installer.main()

    assert status == 1
    assert target.is_symlink()
    assert replacement.read_bytes() == b"target must not be touched"
    launchctl.assert_not_called()
    preflight_mock.assert_not_called()
    assert "differs" in capsys.readouterr().err


def test_matching_files_and_active_jobs_are_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    app = _prepare_app(home)
    destination = home / "Library" / "LaunchAgents"
    destination.mkdir(parents=True)
    rendered = installer._render_templates(home)
    for label, data in rendered.items():
        (destination / f"{label}.plist").write_bytes(data)
    before = {
        label: (destination / f"{label}.plist").read_bytes()
        for label in installer.LABELS
    }
    calls = []

    def launchctl(arguments, *, capture_output, check=False):
        calls.append((arguments, check))
        assert capture_output
        assert arguments[1] == "print"
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight") as preflight_mock,
        patch.object(installer.subprocess, "run", side_effect=launchctl),
        patch.object(installer.http.client, "HTTPConnection", _ready_connection),
    ):
        status = installer.main()

    assert status == 0
    assert [arguments[1] for arguments, _check in calls] == ["print", "print"]
    preflight_mock.assert_not_called()
    for label in installer.LABELS:
        assert (destination / f"{label}.plist").read_bytes() == before[label]


def test_semantically_matching_binary_plist_is_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    app = _prepare_app(home)
    destination = home / "Library" / "LaunchAgents"
    destination.mkdir(parents=True)
    rendered = installer._render_templates(home)
    equivalent = plistlib.dumps(plistlib.loads(rendered[installer.LABELS[0]]), fmt=plistlib.FMT_BINARY)
    target = destination / f"{installer.LABELS[0]}.plist"
    target.write_bytes(equivalent)
    before = target.read_bytes()
    calls = []

    def launchctl(arguments, *, capture_output, check=False):
        calls.append((arguments, check))
        assert capture_output
        assert arguments[1] == "print"
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight") as preflight_mock,
        patch.object(installer.subprocess, "run", side_effect=launchctl),
        patch.object(installer.http.client, "HTTPConnection", _ready_connection),
    ):
        status = installer.main()

    assert status == 0
    assert target.read_bytes() == before
    assert [arguments[1] for arguments, _check in calls] == ["print", "print"]
    preflight_mock.assert_not_called()


def test_bootstraps_both_labels_after_all_validation(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    app = _prepare_app(home)
    calls = []

    def launchctl(arguments, *, capture_output, check=False):
        calls.append((arguments, check))
        assert capture_output
        if arguments[1] == "print":
            return subprocess.CompletedProcess(arguments, 1, stdout=b"", stderr=b"")
        assert arguments[1] == "bootstrap"
        assert check
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight"),
        patch.object(installer.subprocess, "run", side_effect=launchctl),
        patch.object(installer.http.client, "HTTPConnection", _ready_connection),
    ):
        status = installer.main()

    assert status == 0
    assert [arguments[1] for arguments, _check in calls] == [
        "print",
        "print",
        "bootstrap",
        "bootstrap",
    ]
    assert [arguments[-1] for arguments, _check in calls[2:]] == [
        str(home / "Library/LaunchAgents" / f"{label}.plist")
        for label in installer.LABELS
    ]


def test_bootstrap_failure_is_sanitized_and_reports_partial_activation(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    app = _prepare_app(home)
    secret_error = "private launchctl detail that must not be printed"
    bootstrap_count = 0

    def launchctl(arguments, *, capture_output, check=False):
        nonlocal bootstrap_count
        assert capture_output
        if arguments[1] == "print":
            return subprocess.CompletedProcess(arguments, 1, stdout=b"", stderr=b"")
        assert arguments[1] == "bootstrap"
        assert check
        bootstrap_count += 1
        if bootstrap_count == 2:
            raise subprocess.CalledProcessError(
                1,
                arguments,
                stderr=secret_error,
            )
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight"),
        patch.object(installer.subprocess, "run", side_effect=launchctl),
    ):
        status = installer.main()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert status == 1
    assert secret_error not in output
    assert "CalledProcessError" not in output
    assert "traceback" not in output.lower()
    assert "Possible partial activation" in output
    assert installer.LABELS[0] in output
    assert bootstrap_count == 2


@pytest.mark.parametrize("stage", ["request", "getresponse"])
@pytest.mark.parametrize("error_type", [OSError, http.client.HTTPException])
def test_readiness_http_failures_are_sanitized_and_close_connections(
    tmp_path, stage, error_type, capsys
):
    home = tmp_path / "home"
    home.mkdir()
    app = _prepare_app(home)
    connections = []
    secret_error = "private readiness detail that must not be printed"

    def connection_factory(*_args, **_kwargs):
        connection = Mock()
        if stage == "request":
            connection.request.side_effect = error_type(secret_error)
        else:
            connection.getresponse.side_effect = error_type(secret_error)
        connections.append(connection)
        return connection

    def launchctl(arguments, *, capture_output, check=False):
        assert capture_output
        assert arguments[1] == "print"
        return subprocess.CompletedProcess(arguments, 0, stdout=b"", stderr=b"")

    with (
        patch.object(installer.Path, "home", return_value=home),
        patch.object(installer, "APP_PATH", app),
        patch.object(installer, "preflight"),
        patch.object(installer.subprocess, "run", side_effect=launchctl),
        patch.object(installer.http.client, "HTTPConnection", side_effect=connection_factory),
        patch.object(installer.time, "sleep"),
    ):
        status = installer.main()

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert status == 1
    assert secret_error not in output
    assert "traceback" not in output.lower()
    assert len(connections) == 30
    for connection in connections:
        connection.close.assert_called_once()


def test_templates():
    bridge = plistlib.loads((ROOT / "com.stavrobot.imcp.plist").read_bytes())
    assert bridge["KeepAlive"] is True
    assert bridge["ThrottleInterval"] >= 30
    assert bridge["LimitLoadToSessionType"] == "Aqua"
    assert bridge["ProgramArguments"][1].endswith("run_launchd_bridge.py")
    app = plistlib.loads((ROOT / "com.stavrobot.imcp-app.plist").read_bytes())
    assert app["RunAtLoad"] is True
    assert app["ProgramArguments"] == ["/usr/bin/open", "-g", "/Applications/iMCP.app"]


def test_launchagent_template_uses_canonical_plugin_checkout():
    bridge = plistlib.loads((ROOT / "com.stavrobot.imcp.plist").read_bytes())
    checkout = "{{ .chezmoi.homeDir }}/Developer/stavrobot-imcp-plugin"

    assert bridge["WorkingDirectory"] == checkout
    assert bridge["ProgramArguments"] == [
        f"{checkout}/.venv/bin/python",
        f"{checkout}/scripts/run_launchd_bridge.py",
    ]
