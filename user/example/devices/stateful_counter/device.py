from dataclasses import dataclass
from typing import Any

from eos.devices.base_device import BaseDevice


@dataclass
class CounterState:
    """Simple state for the counter."""

    value: int = 0


class StatefulCounter(BaseDevice):
    """Example device that stores state in a dataclass."""

    async def _initialize(self, init_parameters: dict[str, Any]) -> None:
        # Initialize the dataclass state
        self.state = CounterState(value=int(init_parameters.get("initial", 0)))

    async def _cleanup(self) -> None:
        # Nothing to clean up in this simple example
        pass

    async def _report(self) -> dict[str, Any]:
        # Report the current state so it can be inspected via the REST API
        return {"value": self.state.value}

    # Public methods exposed to tasks
    def increment(self, amount: int = 1) -> int:
        """Increment the counter by ``amount`` and return the new value."""
        self.state.value += amount
        return self.state.value

    def decrement(self, amount: int = 1) -> int:
        """Decrement the counter by ``amount`` and return the new value."""
        self.state.value -= amount
        return self.state.value

    def get_state(self) -> dict[str, Any]:
        """Return the current state as a dictionary."""
        return {"value": self.state.value}

    def set_state(self, value: int) -> None:
        """Set the counter to ``value``."""
        self.state.value = int(value)

    def apply_operations(self, ops: list[dict[str, int]]) -> int:
        """Apply a sequence of operations and return the final value."""
        for op in ops:
            action = op.get("action")
            if action == "increment":
                self.increment(int(op.get("amount", 1)))
            elif action == "decrement":
                self.decrement(int(op.get("amount", 1)))
            elif action == "set":
                self.set_state(int(op.get("value", 0)))
        return self.state.value
