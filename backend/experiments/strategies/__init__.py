"""
Strategy registry for auto-discovery.
Just add a new strategy class to any file in experiments/strategies/
and it will be automatically discovered.
"""

import importlib
import inspect
import pkgutil
from typing import Dict, Type

from experiments.strategies.base import DecompositionStrategy


class StrategyRegistry:
    """Auto-discovers and registers all strategy classes"""

    _registry: Dict[str, Type[DecompositionStrategy]] = {}
    _loaded = False

    @classmethod
    def discover_strategies(cls):
        """Scan experiments.strategies module for strategy classes"""
        if cls._loaded:
            return

        import experiments.strategies as strategies_package

        # Iterate through all modules in the strategies package
        for importer, modname, ispkg in pkgutil.iter_modules(
            strategies_package.__path__
        ):
            if modname == "base":  # Skip base module
                continue

            # Import the module
            full_module_name = f"experiments.strategies.{modname}"
            try:
                module = importlib.import_module(full_module_name)

                # Find all DecompositionStrategy subclasses
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, DecompositionStrategy)
                        and obj is not DecompositionStrategy
                        and hasattr(obj, "name")
                    ):

                        # Create instance to get the name
                        try:
                            instance = obj()
                            strategy_name = instance.name
                            cls._registry[strategy_name] = obj
                        except Exception:
                            # Skip if instantiation fails
                            pass
            except Exception as e:
                print(f"Warning: Could not load strategy module {modname}: {e}")

        cls._loaded = True

    @classmethod
    def get_all(cls) -> Dict[str, Type[DecompositionStrategy]]:
        """Get all registered strategies"""
        cls.discover_strategies()
        return cls._registry.copy()

    @classmethod
    def get(cls, name: str) -> Type[DecompositionStrategy]:
        """Get a specific strategy by name"""
        cls.discover_strategies()
        return cls._registry.get(name)

    @classmethod
    def list_names(cls) -> list:
        """List all available strategy names"""
        cls.discover_strategies()
        return list(cls._registry.keys())
