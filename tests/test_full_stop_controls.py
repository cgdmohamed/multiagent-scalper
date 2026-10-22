"""Contract checks for stop-versus-pause behavior (no live exchange API)."""
from app.main import app

def test_stop_start_routes_are_registered():
    paths={(route.path,tuple(sorted(getattr(route,"methods",set())))) for route in app.routes}
    assert any(path=="/control/stop" and "POST" in methods for path,methods in paths)
    assert any(path=="/control/start" and "POST" in methods for path,methods in paths)

def test_stop_is_separate_from_manual_pause():
    from app import main
    assert hasattr(main,"BOT_STOPPED")
    assert hasattr(main,"MANUALLY_PAUSED")
    assert hasattr(main,"BOT_TASKS")
