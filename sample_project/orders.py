from dataclasses import dataclass, field
from datetime import datetime

from notifications import notify_customer
from payment import validate_payment
from utils import normalise_amount


@dataclass
class Order:
    order_id: str
    customer_id: str
    total: float
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_large(self) -> bool:
        return self.total >= 1000


class OrderService:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def create_order(self, customer_id: str, amount: float) -> Order:
        total = normalise_amount(amount)
        if not validate_payment(total, "4111111111111111"):
            raise ValueError("payment rejected")
        order = Order(order_id=f"ord-{len(self._orders) + 1}", customer_id=customer_id, total=total)
        self._orders[order.order_id] = order
        notify_customer(customer_id, order.order_id)
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    async def refund(self, order_id: str) -> bool:
        order = self.get(order_id)
        if order is None:
            return False
        del self._orders[order_id]
        return True
