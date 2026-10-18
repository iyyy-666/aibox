import concurrent.futures
from feature_demo.workers.transport_voice import CachedEngineFactory


def test_reopening_listener_reuses_loaded_engine_without_reopening_a_microphone():
    engines=[]
    class Engine:
        def __init__(self): engines.append(self)
    factory=CachedEngineFactory(Engine)
    first=factory()
    assert factory() is first
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        assert all(item is first for item in pool.map(lambda _:factory(),range(5)))
    assert len(engines)==1
