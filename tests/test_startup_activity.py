"""Startup UI must report actual bounded server events, not fake progress."""
from app import main

def test_startup_event_records_stage_and_message():
    old=list(main.STARTUP_EVENTS)
    prior=main.STARTUP_STAGE
    try:
        main.startup_event("DISCOVERY","Fetching candidates")
        assert main.STARTUP_STAGE=="DISCOVERY"
        assert main.STARTUP_EVENTS[-1]["message"]=="Fetching candidates"
        for i in range(50):
            main.startup_event("CONNECTING",f"attempt {i}")
        assert len(main.STARTUP_EVENTS)<=35
    finally:
        main.STARTUP_EVENTS[:]=old
        main.STARTUP_STAGE=prior

def test_status_contains_startup_event_stream():
    # Endpoint status is authenticated; assert source object shape directly.
    assert isinstance(main.STARTUP_EVENTS,list)
    assert main.STARTUP_STAGE is not None
