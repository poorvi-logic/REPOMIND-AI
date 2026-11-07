import sqlite3

from config import DATABASE_URL


class Database:
    def __init__(self, location: str = DATABASE_URL) -> None:
        self.location = location
        self.connection = sqlite3.connect(":memory:")

    def find_orders(self, customer_id: str) -> list:
        return self.connection.execute(
            f"SELECT order_id, total FROM orders WHERE customer_id = '{customer_id}'"
        ).fetchall()

    def save_order(self, order_id: str, customer_id: str, total: float) -> None:
        self.connection.execute(
            "INSERT INTO orders (order_id, customer_id, total) VALUES (?, ?, ?)",
            (order_id, customer_id, total),
        )
        self.connection.commit()
