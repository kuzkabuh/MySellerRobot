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
