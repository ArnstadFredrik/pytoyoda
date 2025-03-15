"""Models for vehicle sensors."""

from datetime import timedelta
from typing import Any, List, Optional

from pydantic import computed_field

from pytoyoda.const import KILOMETERS_UNIT, MILES_UNIT
from pytoyoda.models.endpoints.electric import (
    ElectricResponseModel,
    ElectricStatusModel,
)
from pytoyoda.models.endpoints.telemetry import TelemetryModel, TelemetryResponseModel
from pytoyoda.models.endpoints.vehicle_health import (
    VehicleHealthModel,
    VehicleHealthResponseModel,
)
from pytoyoda.utils.conversions import convert_distance
from pytoyoda.utils.models import CustomAPIBaseModel, Distance


class Dashboard(CustomAPIBaseModel[Any]):
    """Information that may be found on a vehicles dashboard."""

    def __init__(
        self,
        telemetry: Optional[TelemetryResponseModel] = None,
        electric: Optional[ElectricResponseModel] = None,
        health: Optional[VehicleHealthResponseModel] = None,
        metric: bool = True,
        **kwargs,
    ):
        """Initialise Dashboard model.

        Args:
            telemetry (Optional[TelemetryResponseModel]): Telemetry response model
            electric (Optional[ElectricResponseModel]): Electric response model
            health (Optional[VehicleHealthResponseModel]): Vehicle health response model
            metric (bool): Report distances in metric(or imperial)
            **kwargs: Additional keyword arguments passed to the parent class

        """
        # Create temporary object for data
        data = {
            "telemetry": telemetry,
            "electric": electric,
            "health": health,
            "metric": metric,
        }
        super().__init__(data=data, **kwargs)

        # Get payload data from models
        self._electric: Optional[ElectricStatusModel] = (
            electric.payload if electric else None
        )
        self._telemetry: Optional[TelemetryModel] = (
            telemetry.payload if telemetry else None
        )
        self._health: Optional[VehicleHealthModel] = health.payload if health else None
        self._distance_unit: str = KILOMETERS_UNIT if metric else MILES_UNIT

    @computed_field
    @property
    def odometer(self) -> Optional[float]:
        """Odometer distance.

        Returns:
            float: The latest odometer reading in the current selected units

        """
        if self._telemetry:
            return convert_distance(
                self._distance_unit,
                self._telemetry.odometer.unit,
                self._telemetry.odometer.value,
            )
        return None

    @computed_field
    @property
    def odometer_with_unit(self) -> Optional[Distance]:
        """Odometer distance with unit.

        Returns:
            Distance: The latest odometer reading with unit

        """
        if value := self.odometer:
            return Distance(value=value, unit=self._distance_unit)
        return None

    @computed_field
    @property
    def fuel_level(self) -> Optional[int]:
        """Fuel level.

        Returns:
            int: A value as percentage

        """
        return self._telemetry.fuel_level if self._telemetry else None

    @computed_field
    @property
    def battery_level(self) -> Optional[float]:
        """Shows the battery level if available.

        Returns:
            float: A value as percentage

        """
        return self._electric.battery_level if self._electric else None

    @computed_field
    @property
    def fuel_range(self) -> Optional[float]:
        """The range using _only_ fuel.

        Returns:
            float: The range in the currently selected unit.
                If vehicle is electric returns 0
                If vehicle doesn't support fuel range returns None

        """
        if self._electric and self._electric.fuel_range:
            return convert_distance(
                self._distance_unit,
                self._electric.fuel_range.unit,
                self._electric.fuel_range.value,
            )
        if self._telemetry and self._telemetry.distance_to_empty:
            return convert_distance(
                self._distance_unit,
                self._telemetry.distance_to_empty.unit,
                self._telemetry.distance_to_empty.value,
            )

        return None

    @computed_field
    @property
    def fuel_range_with_unit(self) -> Optional[Distance]:
        """The range using _only_ fuel with unit.

        Returns:
            Distance: The range with current unit

        """
        if value := self.fuel_range:
            return Distance(value=value, unit=self._distance_unit)
        return None

    @computed_field
    @property
    def battery_range(self) -> Optional[float]:
        """The range using _only_ EV.

        Returns:
            float: The range in the currently selected unit.
                If vehicle is fuel only returns None
                If vehicle doesn't support battery range returns None

        """
        if self._electric and self._electric.ev_range:
            return convert_distance(
                self._distance_unit,
                self._electric.ev_range.unit,
                self._electric.ev_range.value,
            )

        return None

    @computed_field
    @property
    def battery_range_with_unit(self) -> Optional[Distance]:
        """The range using _only_ EV with unit.

        Returns:
            Distance: The range with current unit

        """
        if value := self.battery_range:
            return Distance(value=value, unit=self._distance_unit)
        return None

    @computed_field
    @property
    def battery_range_with_ac(self) -> Optional[float]:
        """The range using _only_ EV when using AC.

        Returns:
            float: The range in the currently selected unit.
                If vehicle is fuel only returns 0
                If vehicle doesn't support battery range returns 0

        """
        if self._electric and self._electric.ev_range_with_ac:
            return convert_distance(
                self._distance_unit,
                self._electric.ev_range_with_ac.unit,
                self._electric.ev_range_with_ac.value,
            )

        return None

    @computed_field
    @property
    def battery_range_with_ac_with_unit(self) -> Optional[Distance]:
        """The range using _only_ EV when using AC with unit.

        Returns:
            Distance: The range with current unit

        """
        if value := self.battery_range_with_ac:
            return Distance(value=value, unit=self._distance_unit)
        return None

    @computed_field
    @property
    def range(self) -> Optional[float]:
        """The range using all available fuel & EV.

        Returns:
            float: The range in the currently selected unit.
                fuel only == fuel_range
                ev only == battery_range_with_ac
                hybrid == fuel_range + battery_range_with_ac
                None if not supported

        """
        if self._telemetry and self._telemetry.distance_to_empty:
            return convert_distance(
                self._distance_unit,
                self._telemetry.distance_to_empty.unit,
                self._telemetry.distance_to_empty.value,
            )

        return None

    @computed_field
    @property
    def range_with_unit(self) -> Optional[Distance]:
        """The range using all available fuel & EV with unit.

        Returns:
            Distance: The range with current unit

        """
        if value := self.range:
            return Distance(value=value, unit=self._distance_unit)
        return None

    @computed_field
    @property
    def charging_status(self) -> Optional[str]:
        """Current charging status.

        Returns:
            str: A string containing the charging status as reported
                by the vehicle. None if vehicle doesn't support charging

        """
        return self._electric.charging_status if self._electric else None

    @computed_field
    @property
    def remaining_charge_time(self) -> Optional[timedelta]:
        """Time left until charge is complete.

        Returns:
            timedelta: The amount of time left
                None if vehicle is not currently charging.
                None if vehicle doesn't support charging

        """
        return (
            timedelta(minutes=self._electric.remaining_charge_time)
            if self._electric and self._electric.remaining_charge_time
            else None
        )

    @computed_field
    @property
    def warning_lights(self) -> Optional[List[Any]]:
        """Dashboard Warning Lights.

        Returns:
            List[Any]: List of latest dashboard warning lights
                _Note_ Not fully understood

        """
        return self._health.warning if self._health else None
