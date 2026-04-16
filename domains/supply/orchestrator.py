"""
domains/supply/orchestrator.py
Supply Domain Orchestrator — layered parallel scheduling

Similar to Sherlock's multi-site checking with:
- Layer-based execution (setup → core → fast → secondary)
- ThreadPoolExecutor for parallel execution within layers
- Error isolation per monitor
- Refresh-rate based rerun decisions
"""

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from core.events import EventBus, get_event_bus
from core.types.event import CoffeeEvent
from domains.supply.oni_monitor import ONIMonitor
from domains.supply.cot_monitor import COTMonitor
from domains.supply.ice_monitor import ICECoffeeMonitor
from domains.supply.seasonal_monitor import SeasonalMonitor
from domains.supply.weather_monitor import WeatherMonitor


# Refresh intervals per monitor type (seconds)
REFRESH_INTERVALS: Dict[str, int] = {
    'oni': 86400 * 30,      # 30 days (NOAA monthly update)
    'cot': 86400 * 7,       # 7 days (CFTC weekly Friday release)
    'ice': 86400,           # daily
    'weather': 1800,        # 30 min (OWM free tier ~60 req/min, so 30min is safe)
    'calendar': 86400,      # daily (SeasonalMonitor checks frost window)
}

# Layer definition: monitors that run together in parallel
# Layer 0 (Setup): ONI — slowest, runs first
# Layer 1 (Core): COT + ICE — parallel weekly/daily
# Layer 2 (Fast): Weather — real-time polling (placeholder)
# Layer 3 (Secondary): Seasonal — ultra fast, in-memory
LAYER_MONITORS: Dict[int, List[str]] = {
    0: ['oni'],           # Setup
    1: ['cot', 'ice'],    # Core
    2: ['weather'],       # Fast (OpenWeatherMap, 30min interval)
    3: ['calendar'],      # Seasonal
}

# Alias for clarity
LAYER_0_SETUP = 0
LAYER_1_CORE = 1
LAYER_2_FAST = 2
LAYER_3_SECONDARY = 3


class LayerScheduler:
    """
    Helper class to manage per-monitor last_run times and rerun decisions.
    
    Sherlock equivalence: per-site last_check tracking and rate limiting.
    """

    def __init__(self):
        self._last_run: Dict[str, datetime] = {}

    def record_run(self, monitor_key: str) -> None:
        """Record that a monitor was just run."""
        self._last_run[monitor_key] = datetime.now()

    def should_rerun(self, monitor_key: str, force: bool = False) -> bool:
        """
        Decide if a monitor should run again based on its refresh interval.
        
        Args:
            monitor_key: Key like 'oni', 'cot', 'ice', 'weather', 'calendar'
            force: If True, ignore interval and run anyway (for testing)
            
        Returns:
            True if the monitor should run
        """
        if force:
            return True

        interval = REFRESH_INTERVALS.get(monitor_key, 3600)
        last = self._last_run.get(monitor_key)
        
        if last is None:
            return True  # Never run
        
        elapsed = (datetime.now() - last).total_seconds()
        return elapsed >= interval

    def get_last_run(self, monitor_key: str) -> Optional[datetime]:
        """Get the last run time for a monitor."""
        return self._last_run.get(monitor_key)

    def time_until_next(self, monitor_key: str) -> float:
        """Get seconds until next allowed run (0 if ready)."""
        interval = REFRESH_INTERVALS.get(monitor_key, 3600)
        last = self._last_run.get(monitor_key)
        
        if last is None:
            return 0.0
        
        elapsed = (datetime.now() - last).total_seconds()
        return max(0.0, interval - elapsed)


class SupplyOrchestrator:
    """
    Supply Domain Orchestrator — coordinates multiple monitors with layered scheduling.
    
    Sherlock equivalence:
        - Layer 0 (ONI) = Sherlock site setup
        - Layer 1 (COT+ICE) = Sherlock core site checking
        - Layer 2 (Weather) = Sherlock fast polling sites
        - Layer 3 (Seasonal) = Sherlock secondary/helper sites
    
    Usage:
        orchestrator = SupplyOrchestrator(bus=event_bus, scan_interval=300)
        events = orchestrator.scan_all()
        
        # Or layer by layer:
        orchestrator.scan_layer(0)  # ONI only
        orchestrator.scan_layer(1)  # COT + ICE in parallel
    """

    def __init__(self, bus: Optional[EventBus] = None, scan_interval: int = 300):
        """
        Args:
            bus: EventBus instance. Uses global default if None.
            scan_interval: Main loop interval in seconds (default 300 = 5 min).
        """
        self.bus = bus or get_event_bus()
        self.scan_interval = scan_interval
        self._scheduler = LayerScheduler()
        
        # Thread pool size (matches Sherlock --threads=4 for ON/COT/ICE/Weather)
        self._max_workers = 4
        
        # Lazily initialized monitors dict
        self._monitors: Optional[Dict[str, object]] = None
        
        # Track scan count
        self._scan_count = 0
        self._last_scan_time: Optional[datetime] = None

    def _get_monitors(self) -> Dict[str, object]:
        """
        Lazy-load monitors to avoid circular imports at module load time.
        
        Returns:
            Dict mapping monitor key to monitor instance.
        """
        if self._monitors is not None:
            return self._monitors
        
        from domains.supply.oni_monitor import ONIMonitor
        from domains.supply.cot_monitor import COTMonitor
        from domains.supply.ice_monitor import ICECoffeeMonitor
        from domains.supply.seasonal_monitor import SeasonalMonitor
        
        self._monitors = {
            'oni': ONIMonitor(self.bus),
            'cot': COTMonitor(self.bus),
            'ice': ICECoffeeMonitor(self.bus),
            'weather': WeatherMonitor(self.bus),
            'calendar': SeasonalMonitor(self.bus),
        }

        return self._monitors

    _PLACEHOLDER_MONITORS = set()  # All monitors now implemented

    def _run_monitor(self, monitor_key: str) -> Tuple[str, List[CoffeeEvent]]:
        """
        Run a single monitor with error isolation.
        
        Args:
            monitor_key: Key like 'oni', 'cot', etc.
            
        Returns:
            Tuple of (monitor_key, events_list). Empty list on error.
        """
        monitors = self._get_monitors()
        monitor = monitors.get(monitor_key)
        
        if monitor is None:
            # Placeholder monitor — not implemented yet
            if monitor_key in self._PLACEHOLDER_MONITORS:
                print(f"[{self.__class__.__name__}] ⚠ {monitor_key} monitor not implemented yet, skipping")
            return (monitor_key, [])
        
        try:
            events = monitor.check_and_publish()
            # Normalize: some monitors return single event or None
            if events is None:
                events = []
            elif not isinstance(events, list):
                events = [events]
            
            self._scheduler.record_run(monitor_key)
            return (monitor_key, events)
            
        except Exception as e:
            print(f"[{self.__class__.__name__}] Monitor '{monitor_key}' error: {e}")
            traceback.print_exc()
            return (monitor_key, [])

    def scan_layer(self, layer: int, force: bool = False) -> List[CoffeeEvent]:
        """
        Execute all monitors in a specific layer in parallel.
        
        Args:
            layer: Layer ID (0=Setup, 1=Core, 2=Fast, 3=Secondary)
            force: If True, run even if refresh interval hasn't elapsed
            
        Returns:
            All events produced by monitors in this layer.
        """
        monitor_keys = LAYER_MONITORS.get(layer, [])
        
        if not monitor_keys:
            return []
        
        # Filter to monitors that should run (or force=True)
        runnable = [
            key for key in monitor_keys
            if key in self._get_monitors() and self._scheduler.should_rerun(key, force=force)
        ]
        
        if not runnable:
            # All monitors in this layer are throttled
            return []
        
        all_events: List[CoffeeEvent] = []
        
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(runnable))) as executor:
            futures = {
                executor.submit(self._run_monitor, key): key
                for key in runnable
            }
            
            for future in as_completed(futures):
                monitor_key = futures[future]
                try:
                    key, events = future.result()
                    all_events.extend(events)
                except Exception as e:
                    print(f"[{self.__class__.__name__}] Future error for {monitor_key}: {e}")
        
        return all_events

    def scan_all(self, force: bool = False) -> List[CoffeeEvent]:
        """
        Execute all layers in dependency order (0 → 1 → 2 → 3).
        
        Monitors within a layer run in parallel via ThreadPoolExecutor.
        
        Args:
            force: If True, ignore refresh intervals and run all.
            
        Returns:
            All events produced across all layers.
        """
        self._scan_count += 1
        self._last_scan_time = datetime.now()
        
        all_events: List[CoffeeEvent] = []
        
        # Execute layers in order (0, 1, 2, 3)
        for layer in sorted(LAYER_MONITORS.keys()):
            layer_events = self.scan_layer(layer, force=force)
            all_events.extend(layer_events)
        
        return all_events

    def should_rerun(self, layer: int, last_run: Optional[datetime] = None) -> bool:
        """
        Check if a layer should be rerun based on its monitors' refresh rates.
        
        Sherlock equivalence: site-specific rate limiting.
        
        Args:
            layer: Layer ID
            last_run: Optional previous run time. If None, uses internal tracking.
            
        Returns:
            True if any monitor in the layer is due for a refresh.
        """
        if last_run is None:
            last_run = self._last_scan_time
        
        if last_run is None:
            return True
        
        monitor_keys = LAYER_MONITORS.get(layer, [])
        
        for key in monitor_keys:
            if self._scheduler.should_rerun(key):
                return True
        
        return False

    def time_until_next_scan(self) -> float:
        """
        Get seconds until next scan should occur (0 if ready now).
        """
        if self._last_scan_time is None:
            return 0.0
        
        elapsed = (datetime.now() - self._last_scan_time).total_seconds()
        return max(0.0, self.scan_interval - elapsed)

    def get_status(self) -> Dict:
        """
        Get current orchestrator status for debugging/monitoring.
        
        Returns:
            Dict with per-monitor last run times and time until next run.
        """
        monitors = self._get_monitors()
        status = {
            'scan_count': self._scan_count,
            'last_scan': self._last_scan_time.isoformat() if self._last_scan_time else None,
            'scan_interval': self.scan_interval,
            'time_until_next': self.time_until_next_scan(),
            'monitors': {},
        }
        
        for key in monitors.keys():
            status['monitors'][key] = {
                'last_run': (
                    self._scheduler.get_last_run(key).isoformat()
                    if self._scheduler.get_last_run(key) else None
                ),
                'time_until_next': self._scheduler.time_until_next(key),
                'refresh_interval': REFRESH_INTERVALS.get(key, 0),
            }
        
        return status

    def run(self, duration: Optional[int] = None, verbose: bool = True) -> None:
        """
        Run the orchestrator in a loop.
        
        Args:
            duration: Optional seconds to run. None = run forever (or Ctrl-C).
            verbose: If True, print scan results.
        """
        if verbose:
            print(f"[SupplyOrchestrator] Starting (scan_interval={self.scan_interval}s)")
        
        start_time = datetime.now()
        
        try:
            while True:
                # Check if duration exceeded
                if duration is not None:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= duration:
                        break
                
                # Check if we should scan
                if self.time_until_next_scan() > 0:
                    time.sleep(min(30, self.time_until_next_scan()))  # Wait up to 30s
                    continue
                
                # Execute scan
                events = self.scan_all()
                
                if verbose:
                    print(f"[SupplyOrchestrator] Scan #{self._scan_count}: "
                          f"{len(events)} events from {sum(1 for l in LAYER_MONITORS.keys())} layers")
                
                # Sleep between scans
                time.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            if verbose:
                print(f"\n[SupplyOrchestrator] Stopped (scanned {self._scan_count} times)")


def run():
    """Simple test runner for the orchestrator."""
    from core.events import get_event_bus
    
    print("=== SupplyOrchestrator Test ===\n")
    
    # Create with default event bus
    orchestrator = SupplyOrchestrator(scan_interval=60)
    
    # Show monitor status
    print("Initial status:")
    import json
    print(json.dumps(orchestrator.get_status(), indent=2, default=str))
    
    # Run a single layered scan
    print("\n--- Layer 0 (ONI Setup) ---")
    events = orchestrator.scan_layer(0, force=True)
    print(f"  Events: {len(events)}")
    for ev in events:
        print(f"    {ev}")
    
    print("\n--- Layer 1 (COT+ICE Core) ---")
    events = orchestrator.scan_layer(1, force=True)
    print(f"  Events: {len(events)}")
    for ev in events:
        print(f"    {ev}")
    
    print("\n--- Layer 3 (Seasonal) ---")
    events = orchestrator.scan_layer(3, force=True)
    print(f"  Events: {len(events)}")
    for ev in events:
        print(f"    {ev}")
    
    # Full scan
    print("\n--- Full Scan All Layers ---")
    events = orchestrator.scan_all(force=True)
    print(f"  Total events: {len(events)}")
    
    # Final status
    print("\nFinal status:")
    print(json.dumps(orchestrator.get_status(), indent=2, default=str))
    
    print("\n=== Test Complete ===")


if __name__ == '__main__':
    run()
