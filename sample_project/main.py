from payment import validate_payment
from orders import OrderService
from utils import format_currency


def checkout(amount: float, card_number: str) -> bool:
    """Run a simplified checkout flow."""
    if not validate_payment(amount, card_number):
        return False
    print("Payment accepted")
    return True


def main():
    checkout(250.0, "4111111111111111")
    service = OrderService()
    order = service.create_order("cust-1", 250.0)
    print(format_currency(order.total))


if __name__ == "__main__":
    main()
