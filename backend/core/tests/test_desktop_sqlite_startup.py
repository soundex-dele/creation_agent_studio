import os
from types import SimpleNamespace

import pytest

import desktop_launcher as launcher


@pytest.mark.parametrize('migration_fails', [False, True])
def test_desktop_bootstrap_waits_for_worker_service_before_migrations(monkeypatch, tmp_path, migration_fails):
    events = []
    (tmp_path / 'logs').mkdir()
    monkeypatch.setattr(launcher, 'configure_environment', lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(launcher.multiprocessing, 'freeze_support', lambda: None)
    monkeypatch.setattr(launcher.sys, 'argv', ['desktop_launcher.py'])
    monkeypatch.delenv('SQLITE_WORKER_STARTUP_GATE', raising=False)

    def spawn(mode):
        events.append(('spawn', mode))
        return SimpleNamespace(mode=mode, poll=lambda: None)

    def management(name, *args):
        events.append(('manage', name))
        if name == 'migrate' and migration_fails:
            raise RuntimeError('migration failed')

    def tray(children):
        from pathlib import Path

        assert Path(os.environ['SQLITE_WORKER_STARTUP_GATE']).is_file()
        assert children[0].mode == 'coordinator'
        events.append(('tray', 'ready'))

    monkeypatch.setattr(launcher, '_spawn', spawn)
    monkeypatch.setattr(launcher, '_run_management_command', management)
    monkeypatch.setattr(launcher, '_wait_until_ready', lambda process: process.mode == 'server')
    monkeypatch.setattr(launcher, '_run_tray', tray)
    monkeypatch.setattr(launcher, '_stop_children', lambda children: events.append(('stop', [child.mode for child in children])))
    if migration_fails:
        with pytest.raises(RuntimeError, match='migration failed'):
            launcher.main()
        assert events[-1] == ('stop', ['coordinator'])
    else:
        assert launcher.main() == 0
        assert events[:4] == [('spawn', 'coordinator'), ('manage', 'run_sqlite_service'),
                              ('manage', 'migrate'), ('manage', 'sync_app_center')]
    assert 'SQLITE_WORKER_STARTUP_GATE' not in os.environ
    assert not list((tmp_path / 'logs').glob('*.ready'))


def test_desktop_shutdown_stops_database_owner_last():
    events = []

    def child(name):
        return SimpleNamespace(
            stdin=None, poll=lambda: None,
            terminate=lambda: events.append(('terminate', name)),
            wait=lambda timeout: events.append(('wait', name)),
        )

    launcher._stop_children([child('coordinator'), child('server'), child('scheduler')])
    assert events == [('terminate', 'scheduler'), ('wait', 'scheduler'),
                      ('terminate', 'server'), ('wait', 'server'),
                      ('terminate', 'coordinator'), ('wait', 'coordinator')]
