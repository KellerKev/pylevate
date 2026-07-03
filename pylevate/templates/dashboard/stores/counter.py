from pylevate import Store, action
from pylevate.signals import signal


class CounterStore(Store):
    """Cross-page store. In dev mode its state survives full reloads."""

    count = signal(0)

    @action
    def increment(self):
        self.count = self.count + 1


counter = CounterStore()
