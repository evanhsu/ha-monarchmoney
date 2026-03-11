"""Budget sensors for Monarch Money."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback

from ..const import DOMAIN
from ..entity import MonarchEntity
from ..update_coordinator import MonarchCoordinator
from ..util import format_date
from .base import MonarchSensorEntity

_LOGGER = logging.getLogger(__name__)


class MonarchMoneyCheckingBalanceSensor(MonarchSensorEntity):
    """Checking account balance (sum of depository accounts with subtype checking)."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the checking balance sensor."""
        super().__init__(coordinator, unique_id)
        self._account_data: dict[str, Any] = {}
        self._percentage_of_required_balance: float | None = None
        self._attr_name = "Checking Balance"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_checking_balance"
        self._attr_icon = "mdi:bank"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data
        if not data:
            return

        self._account_data = {}
        matching = [
            a
            for a in data.accounts
            if a.account_type.name == "depository"
            and a.subtype is not None
            and a.subtype.name == "checking"
            and not a.is_hidden
        ]

        for account in matching:
            self._account_data[account.id] = {
                "id": account.id,
                "name": account.display_name,
                "balance": account.display_balance,
                "account_type": account.account_type.name,
                "updated": format_date(account.updated_at) if account.updated_at else "",
                "institution": account.institution.name if account.institution else None,
            }

        try:
            self._state = round(
                sum(
                    a.display_balance
                    for a in matching
                    if a.display_balance is not None
                ),
                2,
            )
        except (TypeError, ValueError):
            self._state = 0

        # Percentage of required checking balance (0-100)
        required = _get_required_checking_balance(self.coordinator)
        if required.total > 0 and self._state is not None:
            pct = min(100.0, max(0.0, (self._state / required.total) * 100))
            self._percentage_of_required_balance = round(pct, 1)
        else:
            self._percentage_of_required_balance = (
                100.0 if (self._state and self._state > 0) else None
            )

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        attrs = dict(self._account_data)
        if self._percentage_of_required_balance is not None:
            attrs["percentage_of_required_balance"] = self._percentage_of_required_balance
        return attrs


def _get_current_month_totals(coordinator: MonarchCoordinator) -> Any:
    """Get budget totals for the current month, or None if not available."""
    data = coordinator.data
    if not data or not data.budget:
        return None
    current_month = datetime.now().strftime("%Y-%m")
    return data.budget.totals_by_month.get(current_month)


@dataclass
class RequiredCheckingBalance:
    """Required checking balance and its component breakdown."""

    total: float
    credit_card_balance: float
    budget_fixed_remaining: float
    budget_flexible_remaining: float
    goals_remaining: float


def _get_required_checking_balance(coordinator: MonarchCoordinator) -> RequiredCheckingBalance:
    """Get required checking balance (credit cards + fixed + flexible + goals remaining)."""
    data = coordinator.data
    if not data:
        return RequiredCheckingBalance(0.0, 0.0, 0.0, 0.0, 0.0)
    credit_accounts = [
        a
        for a in data.accounts
        if a.account_type.name == "credit" and not a.is_hidden
    ]
    try:
        credit_balance = sum(
            a.display_balance
            for a in credit_accounts
            if a.display_balance is not None
        )
    except (TypeError, ValueError):
        credit_balance = 0.0
    totals = _get_current_month_totals(coordinator)
    fixed_remaining = totals.remaining_fixed if totals else 0.0
    flexible_remaining = totals.remaining_flexible if totals else 0.0
    goals_remaining = _get_goals_remaining(coordinator)
    total = credit_balance + fixed_remaining + flexible_remaining + goals_remaining
    return RequiredCheckingBalance(
        total=total,
        credit_card_balance=round(credit_balance, 2),
        budget_fixed_remaining=round(fixed_remaining, 2),
        budget_flexible_remaining=round(flexible_remaining, 2),
        goals_remaining=round(goals_remaining, 2),
    )


def _get_goals_remaining(coordinator: MonarchCoordinator) -> float:
    """Get sum of goals remaining for the current month."""
    data = coordinator.data
    if not data or not data.goals:
        return 0.0
    current_month = datetime.now().strftime("%Y-%m")
    return data.goals.remaining_by_month.get(current_month, 0.0)


def _get_checking_balance(coordinator: MonarchCoordinator) -> float:
    """Get sum of depository accounts with subtype checking."""
    data = coordinator.data
    if not data:
        return 0.0
    matching = [
        a
        for a in data.accounts
        if a.account_type.name == "depository"
        and a.subtype is not None
        and a.subtype.name == "checking"
        and not a.is_hidden
    ]
    try:
        return sum(
            a.display_balance
            for a in matching
            if a.display_balance is not None
        )
    except (TypeError, ValueError):
        return 0.0


class MonarchMoneyBudgetFixedRemainingSensor(MonarchSensorEntity):
    """Budget remaining for fixed expenses this month."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the budget fixed remaining sensor."""
        super().__init__(coordinator, unique_id)
        self._month: str | None = None
        self._planned_amount: float | None = None
        self._actual_amount: float | None = None
        self._attr_name = "Budget Fixed Expenses Remaining"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_budget_fixed_remaining"
        self._attr_icon = "mdi:calendar-check"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        totals = _get_current_month_totals(self.coordinator)
        if totals is None:
            self._state = None
            self._month = None
            self._planned_amount = None
            self._actual_amount = None
        else:
            self._state = round(totals.remaining_fixed, 2)
            self._month = totals.month
            self._planned_amount = round(totals.planned_fixed, 2)
            self._actual_amount = round(totals.actual_fixed, 2)

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "month": self._month,
            "planned_amount": self._planned_amount,
            "actual_amount": self._actual_amount,
        }


class MonarchMoneyBudgetFlexibleRemainingSensor(MonarchSensorEntity):
    """Budget remaining for flexible expenses this month."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the budget flexible remaining sensor."""
        super().__init__(coordinator, unique_id)
        self._month: str | None = None
        self._planned_amount: float | None = None
        self._actual_amount: float | None = None
        self._attr_name = "Budget Flexible Expenses Remaining"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_budget_flexible_remaining"
        self._attr_icon = "mdi:calendar-edit"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        totals = _get_current_month_totals(self.coordinator)
        if totals is None:
            self._state = None
            self._month = None
            self._planned_amount = None
            self._actual_amount = None
        else:
            self._state = round(totals.remaining_flexible, 2)
            self._month = totals.month
            self._planned_amount = round(totals.planned_flexible, 2)
            self._actual_amount = round(totals.actual_flexible, 2)

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "month": self._month,
            "planned_amount": self._planned_amount,
            "actual_amount": self._actual_amount,
        }


class MonarchMoneyBudgetNonMonthlyRemainingSensor(MonarchSensorEntity):
    """Budget remaining for non-monthly expenses this month."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the budget non-monthly remaining sensor."""
        super().__init__(coordinator, unique_id)
        self._month: str | None = None
        self._planned_amount: float | None = None
        self._actual_amount: float | None = None
        self._attr_name = "Budget Non-Monthly Expenses Remaining"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_budget_non_monthly_remaining"
        self._attr_icon = "mdi:calendar-clock"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        totals = _get_current_month_totals(self.coordinator)
        if totals is None:
            self._state = None
            self._month = None
            self._planned_amount = None
            self._actual_amount = None
        else:
            self._state = round(totals.remaining_non_monthly, 2)
            self._month = totals.month
            self._planned_amount = round(totals.planned_non_monthly, 2)
            self._actual_amount = round(totals.actual_non_monthly, 2)

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "month": self._month,
            "planned_amount": self._planned_amount,
            "actual_amount": self._actual_amount,
        }


class MonarchMoneyGoalsRemainingSensor(MonarchSensorEntity):
    """Sum of goals remaining (planned - actual) for the current month."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the goals remaining sensor."""
        super().__init__(coordinator, unique_id)
        self._attr_name = "Goals Remaining"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_goals_remaining"
        self._attr_icon = "mdi:target"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        goals_remaining = _get_goals_remaining(self.coordinator)
        self._state = round(goals_remaining, 2)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()


class MonarchMoneyRequiredCheckingBalanceSensor(MonarchSensorEntity):
    """Required checking balance: credit cards + fixed + flexible budget + goals remaining."""

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the required checking balance sensor."""
        super().__init__(coordinator, unique_id)
        self._required: RequiredCheckingBalance | None = None
        self._attr_name = "Required Checking Balance"
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_required_checking_balance"
        self._attr_icon = "mdi:bank-transfer"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._required = _get_required_checking_balance(self.coordinator)
        self._state = round(self._required.total, 2)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        if self._required is None:
            return {}
        checking_balance = _get_checking_balance(self.coordinator)
        deficit = max(0, round(self._required.total - checking_balance, 2))
        return {
            "credit_card_balance": self._required.credit_card_balance,
            "budget_fixed_remaining": self._required.budget_fixed_remaining,
            "budget_flexible_remaining": self._required.budget_flexible_remaining,
            "goals_remaining": self._required.goals_remaining,
            "checking_balance_deficit": deficit,
        }


class MonarchMoneyBudgetDebugSensor(MonarchEntity, SensorEntity):
    """Debug sensor exposing raw get_budgets API response for troubleshooting."""

    _attr_icon = "mdi:bug"
    _attr_name = "Budget API Debug"

    def __init__(self, coordinator: MonarchCoordinator, unique_id: str) -> None:
        """Initialize the budget debug sensor."""
        super().__init__(coordinator, unique_id)
        self._attr_unique_id = f"{DOMAIN}_{unique_id}_budget_debug"
        self._raw_json: str = ""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data
        if not data or data.budget_raw is None:
            self._attr_native_value = "No data"
            self._raw_json = ""
        else:
            self._attr_native_value = "Available"
            try:
                self._raw_json = json.dumps(data.budget_raw, indent=2)
            except (TypeError, ValueError) as err:
                _LOGGER.warning("Failed to serialize budget_raw: %s", err)
                self._raw_json = str(data.budget_raw)

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw API response as JSON string."""
        return {"raw_response": self._raw_json}
