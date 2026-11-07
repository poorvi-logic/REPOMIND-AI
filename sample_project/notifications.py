import logging

log = logging.getLogger(__name__)


def notify_customer(customer_id: str, order_id: str) -> None:
    log.info("Notify %s about %s", customer_id, order_id)


def describe_order(order_id: str) -> str:
    from orders import OrderService

    order = OrderService().get(order_id)
    return "unknown order" if order is None else f"order {order.order_id} of {order.total}"
