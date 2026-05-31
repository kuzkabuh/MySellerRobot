"""version: 1.0.0
description: Aiogram FSM states for onboarding and account connection flows.
updated: 2026-05-14
"""

from aiogram.fsm.state import State, StatesGroup


class ConnectWildberriesStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_api_key = State()


class ConnectOzonStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_client_id = State()
    waiting_for_api_key = State()


class CostStates(StatesGroup):
    waiting_for_manual_cost = State()
    waiting_for_excel_file = State()


class AdminTariffStates(StatesGroup):
    waiting_for_user_id = State()


class AdminPanelStates(StatesGroup):
    waiting_for_tariff_price = State()
    waiting_for_tariff_limit = State()
    waiting_for_promo_code = State()
    waiting_for_promo_name = State()
    waiting_for_promo_type = State()
    waiting_for_promo_value = State()
    waiting_for_promo_tariffs = State()
    waiting_for_promo_periods = State()
    waiting_for_promo_total_limit = State()
    waiting_for_promo_user_limit = State()
    waiting_for_promo_expires = State()
    waiting_for_promo_new_users = State()
    waiting_for_promo_confirm = State()
    waiting_for_promo_search = State()
    waiting_for_promo_limit_edit = State()
    waiting_for_promo_expires_edit = State()


class PaymentStates(StatesGroup):
    waiting_for_email = State()
    pending_tier_code = State()
    pending_period = State()
    waiting_for_promo_code = State()


class MrcStates(StatesGroup):
    waiting_for_article = State()
    waiting_for_mrc_price = State()
    waiting_for_import_file = State()
    waiting_for_import_confirm = State()
    waiting_for_discount_percent = State()
    waiting_for_price_multiplier = State()
    waiting_for_deviation_percent = State()
