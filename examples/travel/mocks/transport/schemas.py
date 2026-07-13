"""Pydantic schemas for the transport mock API."""

from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    phone: str | None = None
    email: str | None = None


class LoginResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    user: UserOut


class StationOut(BaseModel):
    station_id: str
    name: str
    city: str
    code: str


class TrainSummary(BaseModel):
    train_no: str
    train_type: str
    from_station_id: str
    from_station_name: str
    to_station_id: str
    to_station_name: str
    depart_time: str
    arrive_time: str
    duration_minutes: int


class TrainStopOut(BaseModel):
    station_id: str
    station_name: str
    stop_order: int
    arrive_time: str | None = None
    depart_time: str | None = None


class TrainDetail(TrainSummary):
    description: str
    stops: list[TrainStopOut]


class TrainStatusOut(BaseModel):
    train_no: str
    travel_date: str
    status: str
    planned_departure: str
    planned_arrival: str
    actual_departure: str | None = None
    estimated_arrival: str | None = None
    delay_minutes: int
    reason: str | None = None


class SeatTypeOut(BaseModel):
    seat_type_id: str
    train_no: str
    name: str
    price: float
    description: str


class AvailabilityItem(BaseModel):
    seat_type_id: str
    seat_type_name: str
    available: bool
    available_count: int
    price: float


class AvailabilityOut(BaseModel):
    train_no: str
    travel_date: str
    items: list[AvailabilityItem]


class QuoteRequest(BaseModel):
    train_no: str
    travel_date: str
    seat_type_id: str


class QuoteOut(BaseModel):
    train_no: str
    travel_date: str
    seat_type_id: str
    ticket_price: float
    service_fee: float
    total_price: float
    currency: str = "CNY"


class TripCreateRequest(BaseModel):
    train_no: str
    travel_date: str
    seat_type_id: str
    passenger_name: str
    passenger_phone: str


class PassengerInfoUpdateRequest(BaseModel):
    passenger_name: str | None = None
    passenger_phone: str | None = None


class TripOut(BaseModel):
    trip_id: str
    train_no: str
    train_type: str
    travel_date: str
    seat_type_id: str
    seat_type_name: str
    passenger_name: str
    passenger_phone: str
    from_station_id: str
    from_station_name: str
    to_station_id: str
    to_station_name: str
    status: str
    total_price: float
    created_at: str
    updated_at: str


class PriceBreakdownOut(BaseModel):
    trip_id: str
    ticket_price: float
    service_fee: float
    total_price: float
    currency: str = "CNY"


class TripEventOut(BaseModel):
    status: str
    note: str
    created_at: str


class TripTimelineOut(BaseModel):
    trip_id: str
    events: list[TripEventOut]


class TripSummaryOut(BaseModel):
    total: int
    confirmed: int
    delayed: int
    cancelled: int
    latest_trip: TripOut | None = None


class CancelOut(BaseModel):
    trip_id: str
    status: str
    message: str
