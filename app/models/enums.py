"""version: 1.0.0
description: Domain enum definitions.
updated: 2026-05-14
"""

from enum import StrEnum


class Marketplace(StrEnum):
    WB = "WB"
    OZON = "OZON"


class AccountStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class SaleModel(StrEnum):
    FBS = "FBS"
    FBO = "FBO"
    RFBS = "rFBS"
    DBS = "DBS"
    DBW = "DBW"


class CalculationType(StrEnum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class AlertType(StrEnum):
    LOSS_ORDER = "LOSS_ORDER"
    LOW_MARGIN = "LOW_MARGIN"
    MISSING_COST = "MISSING_COST"
    LOW_STOCK = "LOW_STOCK"
    STOCKOUT_FORECAST = "STOCKOUT_FORECAST"
    FBS_DEADLINE_RISK = "FBS_DEADLINE_RISK"
    LOGISTICS_GROWTH = "LOGISTICS_GROWTH"
    BUYOUT_DROP = "BUYOUT_DROP"
    ORDERS_DROP = "ORDERS_DROP"


class NotificationType(StrEnum):
    NEW_ORDER = "NEW_ORDER"
    DAILY_REPORT = "DAILY_REPORT"
    FBS_CONTROL = "FBS_CONTROL"
    STOCK_ALERT = "STOCK_ALERT"
    PROFIT_ALERT = "PROFIT_ALERT"


class SyncJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
