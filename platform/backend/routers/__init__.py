"""Routers package."""
from . import (
    analyze, result, batch, stocks, reflection, portfolio,
    queue as queue_mod, l1_api as l1_mod, dashboard as dashboard_mod,
    records as records_mod
)

# Alias for cleaner imports
queue = queue_mod
l1_api = l1_mod
dashboard = dashboard_mod
records = records_mod
