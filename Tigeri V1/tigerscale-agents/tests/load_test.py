"""Contain load test backend logic."""
from locust import HttpUser, task, between, constant_pacing, events
import random

# Constant for client ids.
CLIENT_IDS = [f"client_{i:03d}" for i in range(1, 51)]  # 50 clients

# Constant for vendors.
VENDORS = [f"Vendor_{i}" for i in range(1, 200)]
# Constant for payers.
PAYERS  = [f"Payer_{i}"  for i in range(1, 200)]


def random_invoice_text():
    """Execute random invoice text."""
    return (
        f"Invoice from {random.choice(VENDORS)} "
        f"for ${random.randint(100, 99999)} "
        f"due {random.randint(1,28)} next month "
        f"inv #INV-{random.randint(10000, 99999)}"
    )


def random_payment_text():
    """Execute random payment text."""
    return (
        f"Payment received from {random.choice(PAYERS)} "
        f"amount ${random.randint(100, 50000)} "
        f"ref PAY-{random.randint(10000, 99999)}"
    )


def random_expense_text():
    """Execute random expense text."""
    return (
        f"Expense receipt from {random.choice(VENDORS)} "
        f"${random.randint(50, 5000)} "
        f"category {random.choice(['logistics','staff','ops','supplier'])}"
    )


class NormalUser(HttpUser):
    """Sustained normal load."""
    wait_time = between(0.5, 1.5)
    weight = 2

    def on_start(self):
        """Execute on start for NormalUser."""
        self.headers = {"X-Client-ID": random.choice(CLIENT_IDS)}

    @task(4)
    def invoice(self):
        """Execute invoice for NormalUser."""
        self._post(random_invoice_text())

    @task(4)
    def payment(self):
        """Execute payment for NormalUser."""
        self._post(random_payment_text())

    @task(2)
    def expense(self):
        """Execute expense for NormalUser."""
        self._post(random_expense_text())

    @task(1)
    def health(self):
        """Execute health for NormalUser."""
        self.client.get("/health")

    @task(1)
    def health_dlq(self):
        """Execute health dlq for NormalUser."""
        self.client.get("/health/dlq")

    def _post(self, text: str):
        """Execute post for NormalUser."""
        payload = {
            "message": {
                "from": {"id": str(random.randint(100000, 999999))},
                "text": text,
            }
        }
        with self.client.post(
            "/webhooks/telegram",
            json=payload,
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"{resp.status_code}")


class AggressiveUser(HttpUser):
    """High frequency spike user."""
    wait_time = between(0.05, 0.2)
    weight = 5

    def on_start(self):
        """Execute on start for AggressiveUser."""
        self.headers = {"X-Client-ID": random.choice(CLIENT_IDS)}

    @task(5)
    def invoice_spam(self):
        """Execute invoice spam for AggressiveUser."""
        self._post(random_invoice_text())

    @task(5)
    def payment_spam(self):
        """Execute payment spam for AggressiveUser."""
        self._post(random_payment_text())

    @task(2)
    def expense_spam(self):
        """Execute expense spam for AggressiveUser."""
        self._post(random_expense_text())

    def _post(self, text: str):
        """Execute post for AggressiveUser."""
        payload = {
            "message": {
                "from": {"id": str(random.randint(100000, 999999))},
                "text": text,
            }
        }
        with self.client.post(
            "/webhooks/telegram",
            json=payload,
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 429):
                resp.success()
            else:
                resp.failure(f"{resp.status_code}")


class ConstantThroughputUser(HttpUser):
    """Constant pacing — 1 req/sec per user, predictable throughput."""
    wait_time = constant_pacing(1)
    weight = 1

    def on_start(self):
        """Execute on start for ConstantThroughputUser."""
        self.headers = {"X-Client-ID": random.choice(CLIENT_IDS)}

    @task
    def invoice(self):
        """Execute invoice for ConstantThroughputUser."""
        payload = {
            "message": {
                "from": {"id": str(random.randint(100000, 999999))},
                "text": random_invoice_text(),
            }
        }
        with self.client.post(
            "/webhooks/telegram",
            json=payload,
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 429):
                resp.success()
            else:
                resp.failure(f"{resp.status_code}")