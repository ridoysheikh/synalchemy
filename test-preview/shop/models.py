"""Shop models spread over three databases.

``SHOP_SCHEMA_VERSION`` lets the walkthrough evolve the models without editing this
file. Version 2 is "a month later": refunds, customer phone numbers, UTM tracking.
In a real project you would simply edit the classes.
"""

from __future__ import annotations

import enum
import os
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from synalchemy import Model

SCHEMA_VERSION = int(os.environ.get("SHOP_SCHEMA_VERSION", "1"))


def enum_values(cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in cls]


# -- default database: the shop itself ---------------------------------------


class OrderStatus(enum.Enum):
    pending = "pending"
    paid = "paid"
    shipped = "shipped"
    cancelled = "cancelled"
    if SCHEMA_VERSION >= 2:
        refunded = "refunded"
        partially_refunded = "partially_refunded"


class Customer(Model):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(120), unique=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    if SCHEMA_VERSION >= 2:
        phone: Mapped[str | None] = mapped_column(sa.String(30))

    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Product(Model):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(sa.String(32), unique=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    price: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2))
    stock: Mapped[int] = mapped_column(default=0)


class Order(Model):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(sa.ForeignKey("customers.id"))
    status: Mapped[OrderStatus] = mapped_column(
        sa.Enum(OrderStatus, name="order_status", values_callable=enum_values),
        default=OrderStatus.pending,
    )
    total: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(cascade="all, delete-orphan")


class OrderItem(Model):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(sa.ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("products.id"))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2))


# -- analytics database -------------------------------------------------------


class EventKind(enum.Enum):
    page_view = "page_view"
    add_to_cart = "add_to_cart"
    checkout = "checkout"
    if SCHEMA_VERSION >= 2:
        refund = "refund"


class Event(Model):
    __tablename__ = "events"
    __db_name__ = "analytics"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[EventKind] = mapped_column(
        sa.Enum(EventKind, name="event_kind", values_callable=enum_values)
    )
    customer_id: Mapped[int | None]  # no foreign key: customers live in another database
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
    if SCHEMA_VERSION >= 2:
        utm_source: Mapped[str | None] = mapped_column(sa.String(50))


# -- billing database ---------------------------------------------------------


class PaymentStatus(enum.Enum):
    authorized = "authorized"
    captured = "captured"
    refunded = "refunded"


class Payment(Model):
    __tablename__ = "payments"
    __db_name__ = "billing"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(index=True)  # order lives in the default database
    provider: Mapped[str] = mapped_column(sa.String(20))
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(
        sa.Enum(PaymentStatus, name="payment_status", values_callable=enum_values)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())
