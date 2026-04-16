from core.state.engine import DecisionEngine
from core.events.bus import EventBus

class DummyBus(EventBus):
    def __init__(self): pass
    def subscribe(self, *a, **k): pass
    def publish(self, *a, **k): pass
    def get_recent(self, *a, **k): return []
    def get_critical_events(self, *a, **k): return []

engine = DecisionEngine(bus=DummyBus(), use_yaml=False)
report = engine.get_report()
# Check landed cost section appears
assert "Landed Cost" in report or "landed" in report.lower(), "Landed cost section missing"
print("OK — landed cost section present in get_report()")
print()
print(report[:600])
