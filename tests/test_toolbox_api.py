"""Tests for the toolbox API — todos and commands CRUD via route functions."""


def test_todos_crud(tmp_project):
    """Add, list, toggle, and delete todos."""
    from exptrack.dashboard.routes.read_routes import api_get_todos
    from exptrack.dashboard.routes.write_routes import (
        api_add_todo,
        api_delete_todo,
        api_update_todo,
    )

    # Initially empty
    res = api_get_todos()
    assert res["todos"] == []

    # Add a todo
    res = api_add_todo({"text": "Try lr=0.001", "tags": ["ablation"], "study": "lr-sweep"})
    assert res["ok"]
    tid = res["todo"]["id"]
    assert tid.startswith("t_")
    assert res["todo"]["text"] == "Try lr=0.001"
    assert res["todo"]["tags"] == ["ablation"]
    assert res["todo"]["study"] == "lr-sweep"
    assert res["todo"]["done"] is False

    # List shows the todo
    res = api_get_todos()
    assert len(res["todos"]) == 1
    assert res["todos"][0]["id"] == tid

    # Toggle done
    res = api_update_todo({"id": tid, "done": True})
    assert res["ok"]
    res = api_get_todos()
    assert res["todos"][0]["done"] is True

    # Update text and tags
    res = api_update_todo({"id": tid, "text": "New text", "tags": ["new-tag"]})
    assert res["ok"]
    res = api_get_todos()
    assert res["todos"][0]["text"] == "New text"
    assert res["todos"][0]["tags"] == ["new-tag"]

    # Delete
    res = api_delete_todo({"id": tid})
    assert res["ok"]
    res = api_get_todos()
    assert res["todos"] == []


def test_todo_empty_text_rejected(tmp_project):
    """Adding a todo with empty text returns an error."""
    from exptrack.dashboard.routes.write_routes import api_add_todo

    res = api_add_todo({"text": ""})
    assert "error" in res

    res = api_add_todo({"text": "   "})
    assert "error" in res


def test_todo_update_not_found(tmp_project):
    """Updating a non-existent todo returns an error."""
    from exptrack.dashboard.routes.write_routes import api_update_todo

    res = api_update_todo({"id": "t_nonexistent", "done": True})
    assert "error" in res


def test_commands_crud(tmp_project):
    """Add, list, update, and delete commands."""
    from exptrack.dashboard.routes.read_routes import api_get_commands
    from exptrack.dashboard.routes.write_routes import (
        api_add_command,
        api_delete_command,
        api_update_command,
    )

    # Initially empty
    res = api_get_commands()
    assert res["commands"] == []

    # Add a command with tags and study
    res = api_add_command({
        "label": "Train baseline",
        "command": "exptrack run train.py --lr 0.01",
        "tags": ["training"],
        "study": "baseline",
    })
    assert res["ok"]
    cid = res["command"]["id"]
    assert cid.startswith("c_")
    assert res["command"]["label"] == "Train baseline"
    assert res["command"]["command"] == "exptrack run train.py --lr 0.01"
    assert res["command"]["tags"] == ["training"]
    assert res["command"]["study"] == "baseline"

    # List
    res = api_get_commands()
    assert len(res["commands"]) == 1

    # Update label, command, tags, study
    res = api_update_command({
        "id": cid, "label": "Updated", "command": "new cmd",
        "tags": ["eval"], "study": "new-study",
    })
    assert res["ok"]
    res = api_get_commands()
    cmd = res["commands"][0]
    assert cmd["label"] == "Updated"
    assert cmd["command"] == "new cmd"
    assert cmd["tags"] == ["eval"]
    assert cmd["study"] == "new-study"

    # Delete
    res = api_delete_command({"id": cid})
    assert res["ok"]
    res = api_get_commands()
    assert res["commands"] == []


def test_command_empty_rejected(tmp_project):
    """Adding a command with empty text returns an error."""
    from exptrack.dashboard.routes.write_routes import api_add_command

    res = api_add_command({"command": ""})
    assert "error" in res


def test_command_auto_label(tmp_project):
    """Command gets auto-label from first word if label is empty."""
    from exptrack.dashboard.routes.write_routes import api_add_command

    res = api_add_command({"command": "python train.py --epochs 50", "label": ""})
    assert res["ok"]
    assert res["command"]["label"] == "python"


def test_command_update_not_found(tmp_project):
    """Updating a non-existent command returns an error."""
    from exptrack.dashboard.routes.write_routes import api_update_command

    res = api_update_command({"id": "c_nonexistent", "label": "x"})
    assert "error" in res


def test_todos_persist_to_config(tmp_project):
    """Todos are stored in .exptrack/config.json."""
    from exptrack import config as cfg
    from exptrack.dashboard.routes.write_routes import api_add_todo

    api_add_todo({"text": "Check results"})

    # Force config reload
    cfg._cache = None
    conf = cfg.load()
    assert len(conf.get("todos", [])) == 1
    assert conf["todos"][0]["text"] == "Check results"


def test_commands_persist_to_config(tmp_project):
    """Commands are stored in .exptrack/config.json."""
    from exptrack import config as cfg
    from exptrack.dashboard.routes.write_routes import api_add_command

    api_add_command({"command": "ls -la", "label": "list"})

    cfg._cache = None
    conf = cfg.load()
    assert len(conf.get("commands", [])) == 1
    assert conf["commands"][0]["command"] == "ls -la"


def test_multiple_todos_ordering(tmp_project):
    """Multiple todos maintain insertion order."""
    from exptrack.dashboard.routes.read_routes import api_get_todos
    from exptrack.dashboard.routes.write_routes import api_add_todo

    api_add_todo({"text": "First"})
    api_add_todo({"text": "Second"})
    api_add_todo({"text": "Third"})

    res = api_get_todos()
    texts = [t["text"] for t in res["todos"]]
    assert texts == ["First", "Second", "Third"]
