"""What the shop does with its data. Async for request handlers, sync for batch jobs."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa

from shop.models import (
    SCHEMA_VERSION,
    Customer,
    Event,
    EventKind,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
    Product,
)
from synalchemy import RoutingError, SynAlchemy

# One object for the whole app: reads ./synalchemy.toml, engines are created on first use.
db = SynAlchemy.from_config()

CATALOG = [
    ("KB-01", "Mechanical keyboard", "89.90", 50),
    ("MS-02", "Wireless mouse", "24.50", 200),
    ("MN-27", '27" monitor', "249.00", 15),
]
CUSTOMERS = [
    ("ada@example.com", "Ada Lovelace"),
    ("alan@example.com", "Alan Turing"),
    ("grace@example.com", "Grace Hopper"),
]


async def seed() -> list[str]:
    async with db.session() as session:
        if await session.scalar(sa.select(sa.func.count()).select_from(Product)):
            return ["already seeded"]
        session.add_all(
            Product(sku=sku, name=name, price=Decimal(price), stock=stock)
            for sku, name, price, stock in CATALOG
        )
        session.add_all(Customer(email=email, name=name) for email, name in CUSTOMERS)
        await session.commit()
    return [f"{len(CATALOG)} products and {len(CUSTOMERS)} customers -> default database"]


async def place_order(email: str, cart: dict[str, int], provider: str = "stripe") -> list[str]:
    """One session, three databases: order -> default, payment -> billing, event -> analytics."""
    async with db.session() as session:
        customer = await session.scalar(sa.select(Customer).where(Customer.email == email))
        if customer is None:
            raise SystemExit(f"no customer {email!r}; run `python -m shop seed` first")
        products = {
            p.sku: p for p in await session.scalars(sa.select(Product).where(Product.sku.in_(cart)))
        }
        order = Order(customer=customer, status=OrderStatus.paid)
        for sku, quantity in cart.items():
            product = products[sku]
            product.stock -= quantity
            order.items.append(
                OrderItem(product_id=product.id, quantity=quantity, unit_price=product.price)
            )
        order.total = sum((i.unit_price * i.quantity for i in order.items), Decimal("0"))
        session.add(order)
        await session.flush()  # writes to the default database and gives us order.id

        session.add(
            Payment(
                order_id=order.id,
                provider=provider,
                amount=order.total,
                status=PaymentStatus.captured,
            )
        )
        session.add(Event(kind=EventKind.checkout, customer_id=customer.id))
        # Commits each database in turn. This isn't a distributed transaction: if billing
        # failed here, the order would already be committed. Design for that.
        await session.commit()
        return [
            f"order #{order.id} for {customer.name}: {order.total} ({len(order.items)} line items)",
            "  orders + order_items -> default | payments -> billing | events -> analytics",
        ]


async def refund(order_id: int) -> list[str]:
    if SCHEMA_VERSION < 2:
        raise SystemExit("refunds arrive with schema version 2 (SHOP_SCHEMA_VERSION=2)")
    async with db.session() as session:
        order = await session.get(Order, order_id)
        payment = await session.scalar(sa.select(Payment).where(Payment.order_id == order_id))
        if order is None or payment is None:
            raise SystemExit(f"order #{order_id} not found")
        order.status = OrderStatus.refunded
        payment.status = PaymentStatus.refunded
        session.add(Event(kind=EventKind.refund, customer_id=order.customer_id, utm_source="email"))
        await session.commit()
    return [f"order #{order_id} refunded (status uses the new 'refunded' ENUM value)"]


def report() -> list[str]:
    """Nightly report: plain sync code (cron, Celery, a notebook) on the sync engines."""
    lines = []
    with db.sync_session() as session:
        rows = session.execute(
            sa.select(Order.status, sa.func.count(), sa.func.sum(Order.total))
            .group_by(Order.status)
            .order_by(Order.status)
        ).all()
        for status, count, total in rows:
            lines.append(f"orders   {status.value:<20} {count:>3}  {total}")
        captured = session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.captured
            )
        )
        lines.append(f"billing  captured revenue         {captured}")
        for kind, count in session.execute(
            sa.select(Event.kind, sa.func.count()).group_by(Event.kind).order_by(Event.kind)
        ):
            lines.append(f"events   {kind.value:<20} {count:>3}")
    return lines


async def cross_db() -> list[str]:
    """Joins can't cross databases. SynAlchemy says so before anything hits the wire."""
    lines = []
    async with db.session() as session:
        try:
            await session.execute(
                sa.select(Order.id, Payment.amount).join(Payment, Payment.order_id == Order.id)
            )
        except RoutingError as exc:
            lines.append(f"RoutingError: {exc}")
        # the supported way: one query per database, merged in Python
        orders = dict((await session.execute(sa.select(Order.id, Order.status))).all())
        payments = (await session.execute(sa.select(Payment.order_id, Payment.amount))).all()
        for order_id, amount in payments:
            lines.append(f"order #{order_id}: {orders[order_id].value:<10} paid {amount}")
    return lines


async def pools() -> list[str]:
    for name in db.names:
        async with db.engine(name).connect() as conn:
            await conn.execute(sa.select(sa.literal(1)))
    db.sync_engine("default").connect().close()
    lines = []
    for name, status in db.pool_status().items():
        url = db.engine(name.split()[0]).url
        lines.append(f"{name:<16} {url.get_backend_name():<10} {status}")
    return lines
