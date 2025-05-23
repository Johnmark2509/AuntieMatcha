from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
import json
import os
import smtplib
import subprocess
import fcntl
from email.mime.text import MIMEText
from email.message import EmailMessage
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Load email credentials
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

print("EMAIL_ADDRESS:", EMAIL_ADDRESS)
print("EMAIL_PASSWORD:", EMAIL_PASSWORD)

def send_order_notification(subject: str, body: str):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

def git_commit_and_push():
    git_repo = os.getenv("GIT_REPO")
    if not git_repo:
        print("GIT_REPO not set. Skipping git push.")
        return
    try:
        subprocess.run(["git", "config", "--global", "user.email", os.getenv("GIT_EMAIL")], check=True)
        subprocess.run(["git", "config", "--global", "user.name", os.getenv("GIT_USERNAME")], check=True)
        subprocess.run(["git", "add", "orders.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Update orders.json"], check=True)
        subprocess.run(["git", "push", git_repo, "HEAD:main", "--force"], check=True)
        print("✅ orders.json pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print("❌ Git push failed:", e)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def datetimeformat(value, format="%b %d, %I:%M %p"):
    return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime(format)

templates.env.filters["datetimeformat"] = datetimeformat

ORDER_LOG = "orders.json"
ADMIN_PASSWORD = "matchalover"

if not os.path.exists(ORDER_LOG):
    with open(ORDER_LOG, "w") as f:
        json.dump([], f)

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def get_menu(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/order")
async def submit_order(request: Request):
    form = await request.form()

    customer = {
        "name": form.get("customer_name"),
        "contact": form.get("contact_number"),
        "address": form.get("address")
    }

    pickup_date = form.get("pickup_date")
    pickup_time = form.get("pickup_time")
    special_requests = form.get("special_requests")

    items = {}
    drink_toppings = {}
    total = 0

    base_prices = {
        "matcha_classic": 130, "matcha_strawberry": 150, "hojicha_latte": 110, "strawberry_hojicha": 130,
        "matcha_espresso": 150, "iced_americano": 80, "iced_cafe_latte": 95, "iced_spanish_latte": 110,
        "iced_tablea": 100, "tablea_berry": 120, "strawberry_milk": 100,
        "choco_cookie": 60, "strawberry_cookie": 60, "no_bake_cheesecake": 140
    }

    size_prices = { "small": 0, "medium": 30, "to_go": 55 }
    add_on_prices = {
        "strong_matcha": 50, "extra_espresso": 50, "vanilla_foam": 20, "sub_oat_milk": 25,
    }

    drink_ids = [
        "matcha_classic", "matcha_strawberry", "hojicha_latte", "strawberry_hojicha", "matcha_espresso",
        "iced_americano", "iced_cafe_latte", "iced_spanish_latte",
        "iced_tablea", "tablea_berry", "strawberry_milk"
    ]

    for drink_id in drink_ids:
        qty = int(form.get(drink_id, 0))
        if qty > 0:
            items[drink_id] = qty
            drink_toppings[drink_id] = []
            for i in range(qty):
                size = form.get(f"{drink_id}_size_{i}") or "small"
                sweetness = form.get(f"{drink_id}_sweet_{i}", "")
                addons = form.getlist(f"{drink_id}_addon_{i}")

                total += base_prices.get(drink_id, 0)
                total += size_prices.get(size, 0)
                for addon in addons:
                    total += add_on_prices.get(addon, 0)

                drink_toppings[drink_id].append({
                    "size": size,
                    "sweetness": sweetness,
                    "addons": addons
                })

    for pastry in ["choco_cookie", "strawberry_cookie"]:
        qty = int(form.get(pastry, 0))
        if qty > 0:
            items[pastry] = qty
            total += qty * base_prices[pastry]

    cheesecake_qty = int(form.get("no_bake_cheesecake", 0))
    if cheesecake_qty > 0:
        items["no_bake_cheesecake"] = cheesecake_qty
        total += cheesecake_qty * base_prices["no_bake_cheesecake"]
        toppings = []
        for i in range(cheesecake_qty):
            toppings.append(form.get(f"cheesecake_topping_{i}", "plain"))
        drink_toppings["no_bake_cheesecake"] = toppings

    new_order = {
        "timestamp": datetime.now().isoformat(),
        "customer": customer,
        "pickup_date": pickup_date,
        "pickup_time": pickup_time,
        "pickup_datetime": f"{pickup_date}T{pickup_time}",
        "special_requests": special_requests,
        "items": items,
        "drink_toppings": drink_toppings,
        "total": total,
        "status": "Pending"
    }

    try:
        with open(ORDER_LOG, "r", encoding="utf-8") as f:
            orders = json.load(f)
    except:
        orders = []

    orders.append(new_order)

    with open(ORDER_LOG, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        f.truncate()
        json.dump(orders, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)
    git_commit_and_push()

    subject = "📦 New Auntie Matcha Order Received!"
    body = f"""
    New order received from {customer['name']}!

    Contact: {customer['contact']}
    Address: {customer['address']}
    Pickup: {pickup_date} at {pickup_time}
    Total: ₱{total}

    Special Requests: {special_requests or 'None'}
    Items: {json.dumps(items, indent=2)}
    """

    msg = EmailMessage()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = EMAIL_ADDRESS
    msg['Subject'] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print("Failed to send email:", e)

    return RedirectResponse("/", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
def view_orders(request: Request, password: str = ""):
    if password != ADMIN_PASSWORD:
        return HTMLResponse("<h2>Unauthorized 🛑</h2>", status_code=401)

    with open(ORDER_LOG, "r", encoding="utf-8") as f:
        orders = json.load(f)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "orders": orders,
        "password": password
    })

@app.post("/admin/update-status")
async def update_or_delete(
    request: Request,
    index: int = Form(...),
    password: str = Form(...),
    status: str = Form(None),
    action: str = Form(...)
):
    if password != ADMIN_PASSWORD:
        return RedirectResponse(url="/admin?password=wrong", status_code=303)

    with open(ORDER_LOG, "r+", encoding="utf-8") as f:
        orders = json.load(f)

        if 0 <= index < len(orders):
            if action == "update":
                orders[index]["status"] = status
            elif action == "delete":
                del orders[index]
        else:
            print(f"⚠️ Skipping invalid index: {index}. Current orders length: {len(orders)}")

        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        f.truncate()
        json.dump(orders, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)
    git_commit_and_push()

    return RedirectResponse(url=f"/admin?password={password}", status_code=303)
