"""Unified feature demo application for the RK3588 AI experiment box."""

from .models import ModuleDefinition, ModuleState
from .registry import MODULES, get_module

__all__ = ["MODULES", "ModuleDefinition", "ModuleState", "get_module"]
