import sqlite3
from app.historical_research import load,store,replay

def test_empty_database_has_no_candles(tmp_path):
    assert load(tmp_path/"research.sqlite3","BTCUSDT","1")==[]

def test_store_is_idempotent_and_time_sorted(tmp_path):
    db=tmp_path/"research.sqlite3"
    rows=[(60000,100,102,99,101,50),(0,100,101,99,100,50)]
    store(db,"BTCUSDT","1",rows)
    store(db,"BTCUSDT","1",rows)
    result=load(db,"BTCUSDT","1")
    assert len(result)==2 and result[0][0]==0

def test_replay_fails_closed_on_short_history():
    result=replay([(0,100,100,100,100,1)])
    assert result["trades"]==0
    assert "INSUFFICIENT_HISTORY" in result["warnings"]

def test_stop_first_when_both_levels_touched():
    bars=[]
    for i in range(50):
        c=100 if i<20 else 102
        bars.append((i*60000,c,c+3,c-3,c,100))
    result=replay(bars)
    assert result["trades"]>0
    assert result["net_pct"]<0
