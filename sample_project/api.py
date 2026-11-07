import asyncio
from typing import Callable

from auth import require_token
from orders import OrderService

service = OrderService()


class Router:
    def __init__(self) -> None:
        self.routes: dict[str, Callable] = {}

    def route(self, path: str) -> Callable:
        def register(handler: Callable) -> Callable:
            self.routes[path] = handler
            return handler

        return register


router = Router()


@router.route("/orders")
async def list_orders(token: str | None = None) -> dict:
    if not require_token(token):
        return {"status": 401}
    return {"status": 200, "orders": []}


@router.route("/refund")
async def refund_order(order_id: str, token: str | None = None) -> dict:
    try:
        refunded = await service.refund(order_id)
    except:
        return {"status": 500}
    return {"status": 200 if refunded else 404}


def parse_quantity(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        pass
    return 1


async def dispatch(path: str, **kwargs) -> dict:
    handler = router.routes.get(path)
    if handler is None:
        return {"status": 404}
    return await handler(**kwargs)


def start() -> None:
    asyncio.run(dispatch("/orders", token="demo"))
