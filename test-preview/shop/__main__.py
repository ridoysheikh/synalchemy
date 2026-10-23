"""``python -m shop <command>``: run one piece of the demo by hand."""

from __future__ import annotations

import argparse
import asyncio
import inspect

from shop import services


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m shop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="add products and customers")
    order = sub.add_parser("order", help="place an order: EMAIL SKU:QTY [SKU:QTY ...]")
    order.add_argument("email")
    order.add_argument("items", nargs="+")
    order.add_argument("--provider", default="stripe")
    refund = sub.add_parser("refund", help="refund an order (schema version 2)")
    refund.add_argument("order_id", type=int)
    sub.add_parser("report", help="sync report over all three databases")
    sub.add_parser("cross-db", help="show what happens with a cross-database join")
    sub.add_parser("pools", help="show the connection pools in use")
    args = parser.parse_args()

    if args.command == "order":
        cart = {sku: int(qty) for sku, qty in (item.split(":") for item in args.items)}
        call = services.place_order(args.email, cart, args.provider)
    elif args.command == "refund":
        call = services.refund(args.order_id)
    else:
        call = getattr(services, args.command.replace("-", "_"))()

    async def run() -> list[str]:
        try:
            return await call if inspect.isawaitable(call) else call
        finally:
            await services.db.dispose()

    for line in asyncio.run(run()):
        print(line)


if __name__ == "__main__":
    main()
