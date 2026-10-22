from app.main import subscription_batches


def test_five_pairs_split_into_valid_bybit_spot_batches():
    symbols=["BTCUSDT","ETHUSDT","SOLUSDT","ENAUSDT","NEARUSDT"]
    batches=subscription_batches(symbols)
    assert sum(map(len,batches)) == 15
    assert [len(x) for x in batches] == [10,5]
    assert all(len(x)<=10 for x in batches)
    assert len({x for batch in batches for x in batch}) == 15
