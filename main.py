import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Orders API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

TOTAL_ORDERS = 55
RATE_LIMIT = 17
WINDOW = 10  # seconds

# Fixed catalog of order IDs 1..55
orders_catalog = [{"id": i} for i in range(1, TOTAL_ORDERS + 1)]

# Stores created orders by idempotency key
idempotency_store = {}

# Rate limit buckets
client_buckets = defaultdict(deque)


class OrderCreate(BaseModel):
    item: str | None = None
    quantity: int = 1


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Skip browser preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "anonymous")

    now = time.time()
    bucket = client_buckets[client]

    # Remove expired timestamps
    while bucket and bucket[0] <= now - WINDOW:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT:
        retry_after = max(1, int(WINDOW - (now - bucket[0])) + 1)

        return Response(
            status_code=429,
            headers={
                "Retry-After": str(retry_after)
            },
        )

    bucket.append(now)

    return await call_next(request)


@app.post("/orders")
def create_order(
    order: OrderCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    # Idempotent POST
    if idempotency_key in idempotency_store:
        response.status_code = status.HTTP_200_OK
        return idempotency_store[idempotency_key]

    created = {
        "id": str(uuid.uuid4()),
        "item": order.item,
        "quantity": order.quantity,
    }

    idempotency_store[idempotency_key] = created

    response.status_code = status.HTTP_201_CREATED
    return created


@app.get("/orders")
def list_orders(limit: int = 10, cursor: str | None = None):
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        start = 0

    # Never return more than requested
    limit = max(1, min(limit, TOTAL_ORDERS))

    end = min(start + limit, TOTAL_ORDERS)

    items = orders_catalog[start:end]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = str(end)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Orders API",
    }
