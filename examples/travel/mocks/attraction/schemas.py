"""Pydantic schemas for the attraction mock API."""

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


class AttractionSummary(BaseModel):
    attraction_id: str
    name: str
    city: str
    address: str
    phone: str
    description: str


class AttractionDetail(AttractionSummary):
    opening_hours: str
    entry_note: str


class PoliciesOut(BaseModel):
    attraction_id: str
    entry_policy: str
    late_entry_policy: str
    reschedule_policy: str
    cancellation_policy: str


class TicketTypeSummary(BaseModel):
    ticket_type_id: str
    attraction_id: str
    name: str
    audience: str
    base_price: float


class TicketTypeDetail(TicketTypeSummary):
    description: str


class AvailabilityItem(BaseModel):
    ticket_type_id: str
    ticket_type_name: str
    entry_slot: str
    available: bool
    available_count: int
    price: float


class AvailabilityOut(BaseModel):
    attraction_id: str
    visit_date: str
    items: list[AvailabilityItem]


class QuoteRequest(BaseModel):
    attraction_id: str
    ticket_type_id: str
    visit_date: str
    entry_slot: str


class QuoteOut(BaseModel):
    attraction_id: str
    ticket_type_id: str
    visit_date: str
    entry_slot: str
    ticket_price: float
    service_fee: float
    total_price: float
    currency: str = "CNY"


class TicketCreateRequest(BaseModel):
    attraction_id: str
    ticket_type_id: str
    visit_date: str
    entry_slot: str
    visitor_name: str
    visitor_phone: str
    trip_id: str | None = None


class VisitorInfoUpdateRequest(BaseModel):
    visitor_name: str | None = None
    visitor_phone: str | None = None


class TicketOut(BaseModel):
    ticket_id: str
    attraction_id: str
    attraction_name: str
    ticket_type_id: str
    ticket_type_name: str
    trip_id: str | None = None
    visitor_name: str
    visitor_phone: str
    visit_date: str
    entry_slot: str
    status: str
    total_price: float
    created_at: str
    updated_at: str


class PriceBreakdownOut(BaseModel):
    ticket_id: str
    ticket_price: float
    service_fee: float
    total_price: float
    currency: str = "CNY"


class TicketEventOut(BaseModel):
    status: str
    note: str
    created_at: str


class TicketTimelineOut(BaseModel):
    ticket_id: str
    events: list[TicketEventOut]


class TicketSummaryOut(BaseModel):
    total: int
    confirmed: int
    cancelled: int
    latest_ticket: TicketOut | None = None


class CancelOut(BaseModel):
    ticket_id: str
    status: str
    message: str
