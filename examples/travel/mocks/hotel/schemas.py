"""Pydantic schemas for the hotel mock API."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class HotelSummary(BaseModel):
    hotel_id: str
    name: str
    city: str
    address: str
    phone: str
    description: str


class HotelDetail(HotelSummary):
    check_in_time: str
    check_out_time: str
    late_arrival_hold_until: str
    cancellation_policy: str
    check_in_note: str


class FacilitiesOut(BaseModel):
    hotel_id: str
    facilities: list[str]


class PoliciesOut(BaseModel):
    hotel_id: str
    check_in_time: str
    check_out_time: str
    late_arrival_hold_until: str
    cancellation_policy: str
    check_in_note: str


class ReviewOut(BaseModel):
    author: str
    rating: float
    comment: str


class RoomTypeSummary(BaseModel):
    room_type_id: str
    hotel_id: str
    name: str
    bed_type: str
    area_sqm: float
    max_guests: int
    base_price: float


class RoomTypeDetail(RoomTypeSummary):
    description: str


class AvailabilityItem(BaseModel):
    room_type_id: str
    room_type_name: str
    available: bool
    available_count: int
    nightly_price: float
    total_nights: int
    total_price: float


class AvailabilityOut(BaseModel):
    hotel_id: str
    check_in: str
    check_out: str
    items: list[AvailabilityItem]


class QuoteRequest(BaseModel):
    hotel_id: str
    room_type_id: str
    check_in: str
    check_out: str


class QuoteOut(BaseModel):
    hotel_id: str
    room_type_id: str
    check_in: str
    check_out: str
    nights: int
    room_subtotal: float
    tax_rate: float
    tax_amount: float
    total_price: float
    currency: str = "CNY"


class BookingCreateRequest(BaseModel):
    hotel_id: str
    room_type_id: str
    check_in: str
    check_out: str
    guest_name: str
    guest_phone: str
    trip_id: str | None = None


class GuestInfoUpdateRequest(BaseModel):
    guest_name: str | None = None
    guest_phone: str | None = None


class BookingOut(BaseModel):
    booking_id: str
    hotel_id: str
    hotel_name: str
    room_type_id: str
    room_type_name: str
    trip_id: str | None = None
    guest_name: str
    guest_phone: str
    check_in: str
    check_out: str
    status: str
    total_price: float
    created_at: str
    updated_at: str


class PriceBreakdownOut(BaseModel):
    booking_id: str
    nights: int
    room_rate: float
    room_subtotal: float
    tax_rate: float
    tax_amount: float
    total_price: float
    currency: str = "CNY"


class BookingSummaryOut(BaseModel):
    total: int
    confirmed: int
    cancelled: int
    latest_booking: BookingOut | None = None


class CancelOut(BaseModel):
    booking_id: str
    status: str
    message: str
