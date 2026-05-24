from src.cli import main


def test_normalize_config_path_expands_user(monkeypatch, tmp_path):
    home = tmp_path / "home"
    config_dir = home / "ao"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text("{}")
    monkeypatch.setenv("HOME", str(home))

    assert main.normalize_config_path("~/ao/config.json") == str(
        config_file.resolve()
    )


def test_normalize_config_path_resolves_relative_paths(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.chdir(tmp_path)

    assert main.normalize_config_path("config.json") == str(
        config_file.resolve()
    )


def test_cli_loads_config_with_normalized_path(monkeypatch, tmp_path, capsys):
    loaded_paths = []
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.chdir(tmp_path)

    class FakeConfig:
        def __init__(self, path=None):
            loaded_paths.append(path)

    monkeypatch.setattr(main, "Config", FakeConfig)
    monkeypatch.setattr(
        "sys.argv",
        ["ao", "--config", "config.json", "status"],
    )

    config = main.cli()

    assert isinstance(config, FakeConfig)
    assert loaded_paths == [str(config_file.resolve())]
    assert "Checking agent status" in capsys.readouterr().out


def test_cli_without_config_preserves_default_config(monkeypatch):
    loaded_paths = []

    class FakeConfig:
        def __init__(self, path=None):
            loaded_paths.append(path)

    monkeypatch.setattr(main, "Config", FakeConfig)
    monkeypatch.setattr("sys.argv", ["ao", "status"])

    main.cli()

    assert loaded_paths == [None]
