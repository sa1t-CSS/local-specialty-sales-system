import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "sales.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-specialty-sales-dev-key")

LOW_STOCK_THRESHOLD = 20
DEFAULT_CATEGORIES = [
    ("水果类", "新鲜水果及地方特色水果"),
    ("生鲜类", "蔬菜、水产及其他新鲜农产品"),
    ("粮油类", "大米、杂粮、面粉和食用油"),
    ("肉禽蛋类", "肉制品、禽类和蛋类农产品"),
    ("菌菇类", "鲜菌、干菌、木耳等菌菇产品"),
    ("坚果干果类", "坚果、果干和地方特色干果"),
    ("茶饮类", "茶叶、花茶和地方特色饮品"),
    ("调味干货类", "香料、调味品和其他干货"),
]


def migrate_database(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO categories (name, description) VALUES (?, ?)",
        DEFAULT_CATEGORIES,
    )
    category_ids = {
        row["name"]: row["id"]
        for row in conn.execute("SELECT id, name FROM categories").fetchall()
    }

    legacy_defaults = {
        "新疆特产": "坚果干果类",
        "云南菌菇": "菌菇类",
        "东北山珍": "菌菇类",
        "岭南干货": "调味干货类",
    }
    fruit_keywords = ("果", "枣", "梨", "桃", "橙", "柑", "莓", "瓜", "葡萄")
    mushroom_keywords = ("菌", "菇", "木耳")

    for table in ("products", "product_applications"):
        rows = conn.execute(
            f"""
            SELECT item.id, item.name, c.name AS category_name
            FROM {table} item
            JOIN categories c ON c.id = item.category_id
            WHERE c.name IN ('新疆特产', '云南菌菇', '东北山珍', '岭南干货')
            """
        ).fetchall()
        for row in rows:
            if any(keyword in row["name"] for keyword in fruit_keywords):
                target = "水果类"
            elif any(keyword in row["name"] for keyword in mushroom_keywords):
                target = "菌菇类"
            else:
                target = legacy_defaults[row["category_name"]]
            conn.execute(
                f"UPDATE {table} SET category_id = ? WHERE id = ?",
                (category_ids[target], row["id"]),
            )

    conn.execute(
        """
        DELETE FROM categories
        WHERE name IN ('新疆特产', '云南菌菇', '东北山珍', '岭南干货')
          AND id NOT IN (SELECT category_id FROM products)
          AND id NOT IN (SELECT category_id FROM product_applications)
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO merchant_order_fulfillments (order_id, merchant_id, status)
        SELECT DISTINCT oi.order_id, p.merchant_id,
               CASE WHEN o.status IN ('shipped', 'completed') THEN 'shipped' ELSE 'new' END
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        JOIN orders o ON o.id = oi.order_id
        """
    )


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_database():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema)

        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            users = [
                ("admin", generate_password_hash("admin123"), "admin", "系统管理员", "13800000000"),
                ("seller01", generate_password_hash("seller123"), "merchant", "示例商家", "13800000001"),
                ("consumer01", generate_password_hash("user123"), "consumer", "示例消费者", "13800000002"),
            ]
            conn.executemany(
                "INSERT INTO users (username, password_hash, role, display_name, phone) VALUES (?, ?, ?, ?, ?)",
                users,
            )

        if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            conn.executemany("INSERT INTO categories (name, description) VALUES (?, ?)", DEFAULT_CATEGORIES)

        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            merchant = conn.execute("SELECT id FROM users WHERE username = 'seller01'").fetchone()
            categories = {
                row["name"]: row["id"]
                for row in conn.execute("SELECT id, name FROM categories").fetchall()
            }
            if merchant:
                products = [
                    (
                        merchant["id"],
                        categories["水果类"],
                        "新疆灰枣",
                        "新疆阿克苏",
                        29.90,
                        120,
                        36,
                        "https://images.unsplash.com/photo-1601493700631-2b16ec4b4716?auto=format&fit=crop&w=900&q=80",
                        "果肉饱满，适合煲汤、泡茶和日常零食。",
                        "active",
                    ),
                    (
                        merchant["id"],
                        categories["菌菇类"],
                        "云南干巴菌礼盒",
                        "云南昆明",
                        88.00,
                        48,
                        18,
                        "https://images.unsplash.com/photo-1504545102780-26774c1bb073?auto=format&fit=crop&w=900&q=80",
                        "精选菌菇干货，适合炖汤和家庭宴席。",
                        "active",
                    ),
                    (
                        merchant["id"],
                        categories["菌菇类"],
                        "东北黑木耳",
                        "黑龙江牡丹江",
                        39.80,
                        90,
                        52,
                        "https://images.unsplash.com/photo-1606756790138-261d2b21cd75?auto=format&fit=crop&w=900&q=80",
                        "泡发率高，口感脆嫩，适合凉拌和炒菜。",
                        "active",
                    ),
                    (
                        merchant["id"],
                        categories["调味干货类"],
                        "新会陈皮",
                        "广东江门",
                        66.00,
                        35,
                        24,
                        "https://images.unsplash.com/photo-1615484477778-ca3b77940c25?auto=format&fit=crop&w=900&q=80",
                        "香气醇厚，可泡茶、煲汤、入菜。",
                        "active",
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO products
                    (merchant_id, category_id, name, origin, price, stock, sales, image_url, description, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    products,
                )
        migrate_database(conn)
        conn.commit()
    finally:
        conn.close()


@app.before_request
def load_user():
    init_database_once()
    user_id = session.get("user_id")
    g.user = None
    if user_id:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def init_database_once():
    if not app.config.get("DATABASE_READY"):
        init_database()
        app.config["DATABASE_READY"] = True


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("请先登录。")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


@app.context_processor
def inject_globals():
    return {
        "current_user": g.get("user"),
        "role_names": {
            "consumer": "消费者",
            "merchant": "商家",
            "admin": "管理员",
        },
        "status_names": {
            "active": "已上架",
            "inactive": "已下架",
            "pending": "待审核",
            "approved": "已批准",
            "rejected": "已驳回",
        },
        "application_type_names": {
            "create": "新增商品",
            "update": "修改商品",
            "list": "申请上架",
            "delist": "申请下架",
        },
        "order_status_names": {
            "submitted": "已提交",
            "paid": "已付款",
            "shipped": "已发货",
            "completed": "已完成",
            "cancelled": "已取消",
        },
        "fulfillment_status_names": {
            "new": "待商家处理",
            "shipment_requested": "待管理员审批发货",
            "shipped": "已批准发货",
            "rejected": "发货申请已驳回",
        },
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
    }


def fetch_categories():
    return get_db().execute("SELECT * FROM categories ORDER BY name").fetchall()


def parse_product_form(default_status="active"):
    name = request.form.get("name", "").strip()
    origin = request.form.get("origin", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    status = request.form.get("requested_status", default_status)
    category_id_raw = request.form.get("category_id", "")
    price_raw = request.form.get("price", "")
    stock_raw = request.form.get("stock", "")

    if not name:
        return None, "商品名称不能为空。"
    if status not in {"active", "inactive"}:
        return None, "商品状态不正确。"

    try:
        category_id = int(category_id_raw)
    except ValueError:
        return None, "请选择商品分类。"

    category = get_db().execute("SELECT id FROM categories WHERE id = ?", (category_id,)).fetchone()
    if category is None:
        return None, "商品分类不存在。"

    try:
        price = round(float(price_raw), 2)
    except ValueError:
        return None, "价格必须是数字。"
    if price <= 0:
        return None, "价格必须大于 0。"

    try:
        stock = int(stock_raw)
    except ValueError:
        return None, "库存必须是整数。"
    if stock < 0:
        return None, "库存不能小于 0。"

    return {
        "name": name,
        "category_id": category_id,
        "origin": origin,
        "price": price,
        "stock": stock,
        "image_url": image_url,
        "description": description,
        "requested_status": status,
    }, None


def product_to_application_data(product, requested_status=None):
    return {
        "name": product["name"],
        "category_id": product["category_id"],
        "origin": product["origin"],
        "price": product["price"],
        "stock": product["stock"],
        "image_url": product["image_url"],
        "description": product["description"],
        "requested_status": requested_status or product["status"],
    }


def insert_application(merchant_id, product_id, application_type, data):
    db = get_db()
    if product_id is None:
        existing_product = db.execute(
            "SELECT id FROM products WHERE merchant_id = ? AND name = ?",
            (merchant_id, data["name"]),
        ).fetchone()
        pending_application = db.execute(
            """
            SELECT id FROM product_applications
            WHERE merchant_id = ? AND product_id IS NULL AND name = ? AND status = 'pending'
            """,
            (merchant_id, data["name"]),
        ).fetchone()
        if existing_product or pending_application:
            return "同名商品或待审核的新增商品申报已存在，请勿重复提交。"
    else:
        pending_application = db.execute(
            "SELECT id FROM product_applications WHERE product_id = ? AND status = 'pending'",
            (product_id,),
        ).fetchone()
        if pending_application:
            return "该商品已有待审核申报，请等待审核完成后再提交新的变更。"

    db.execute(
        """
        INSERT INTO product_applications
        (merchant_id, product_id, application_type, name, category_id, origin, price, stock,
         image_url, description, requested_status, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            merchant_id,
            product_id,
            application_type,
            data["name"],
            data["category_id"],
            data["origin"],
            data["price"],
            data["stock"],
            data["image_url"],
            data["description"],
            data["requested_status"],
        ),
    )
    db.commit()
    return None


@app.route("/")
def index():
    db = get_db()
    keyword = request.args.get("keyword", "").strip()
    category_id = request.args.get("category_id", "").strip()
    sort = request.args.get("sort", "sales_desc")

    sql = """
        SELECT p.*, c.name AS category_name, u.display_name AS merchant_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        JOIN users u ON u.id = p.merchant_id
        WHERE p.status = 'active' AND p.stock > 0
    """
    params = []
    if keyword:
        sql += " AND (p.name LIKE ? OR p.origin LIKE ? OR p.description LIKE ?)"
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)

    order_by = {
        "price_asc": "p.price ASC",
        "price_desc": "p.price DESC",
        "sales_desc": "p.sales DESC",
        "stock_desc": "p.stock DESC",
        "newest": "p.created_at DESC",
    }.get(sort, "p.sales DESC")
    sql += f" ORDER BY {order_by}"
    products = db.execute(sql, params).fetchall()
    return render_template(
        "index.html",
        products=products,
        categories=fetch_categories(),
        keyword=keyword,
        selected_category=category_id,
        sort=sort,
    )


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = get_db().execute(
        """
        SELECT p.*, c.name AS category_name, u.display_name AS merchant_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        JOIN users u ON u.id = p.merchant_id
        WHERE p.id = ? AND p.status = 'active'
        """,
        (product_id,),
    ).fetchone()
    if product is None:
        abort(404)
    return render_template("product_detail.html", product=product)


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "consumer")

        if role not in {"consumer", "merchant"}:
            flash("注册角色不正确。")
        elif not username or not password or not display_name:
            flash("用户名、密码和名称不能为空。")
        elif len(password) < 6:
            flash("密码长度至少 6 位。")
        else:
            try:
                get_db().execute(
                    """
                    INSERT INTO users (username, password_hash, role, display_name, phone)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, generate_password_hash(password), role, display_name, phone),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                flash("用户名已存在。")
            else:
                flash("注册成功，请登录。")
                return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("用户名或密码错误。")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash("登录成功。")
            next_url = request.args.get("next")
            if user["role"] == "admin":
                return redirect(next_url or url_for("admin_dashboard"))
            if user["role"] == "merchant":
                return redirect(next_url or url_for("merchant_dashboard"))
            return redirect(next_url or url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录。")
    return redirect(url_for("index"))


@app.route("/cart")
@role_required("consumer")
def cart():
    items = get_db().execute(
        """
        SELECT ci.id AS cart_id, ci.quantity, p.id AS product_id, p.name, p.price, p.stock,
               p.image_url, p.status, u.display_name AS merchant_name
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        JOIN users u ON u.id = p.merchant_id
        WHERE ci.user_id = ?
        ORDER BY ci.id DESC
        """,
        (g.user["id"],),
    ).fetchall()
    total = sum(item["price"] * item["quantity"] for item in items)
    return render_template("cart.html", items=items, total=total)


@app.post("/cart/add/<int:product_id>")
@role_required("consumer")
def add_to_cart(product_id):
    quantity = request.form.get("quantity", "1")
    try:
        quantity = max(1, int(quantity))
    except ValueError:
        quantity = 1

    product = get_db().execute(
        "SELECT * FROM products WHERE id = ? AND status = 'active'", (product_id,)
    ).fetchone()
    if product is None:
        flash("商品不存在或已下架。")
        return redirect(url_for("index"))
    if product["stock"] < quantity:
        flash("库存不足。")
        return redirect(url_for("product_detail", product_id=product_id))

    db = get_db()
    existing = db.execute(
        "SELECT * FROM cart_items WHERE user_id = ? AND product_id = ?",
        (g.user["id"], product_id),
    ).fetchone()
    if existing:
        new_quantity = min(product["stock"], existing["quantity"] + quantity)
        db.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (new_quantity, existing["id"]))
    else:
        db.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)",
            (g.user["id"], product_id, quantity),
        )
    db.commit()
    flash("已加入购物车。")
    return redirect(url_for("cart"))


@app.post("/cart/update/<int:cart_id>")
@role_required("consumer")
def update_cart(cart_id):
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 1
    db = get_db()
    item = db.execute(
        """
        SELECT ci.*, p.stock
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE ci.id = ? AND ci.user_id = ?
        """,
        (cart_id, g.user["id"]),
    ).fetchone()
    if item is None:
        abort(404)
    if quantity <= 0:
        db.execute("DELETE FROM cart_items WHERE id = ?", (cart_id,))
    else:
        db.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (min(quantity, item["stock"]), cart_id))
    db.commit()
    flash("购物车已更新。")
    return redirect(url_for("cart"))


@app.post("/cart/delete/<int:cart_id>")
@role_required("consumer")
def delete_cart_item(cart_id):
    get_db().execute("DELETE FROM cart_items WHERE id = ? AND user_id = ?", (cart_id, g.user["id"]))
    get_db().commit()
    flash("已删除购物车商品。")
    return redirect(url_for("cart"))


@app.post("/checkout")
@role_required("consumer")
def checkout():
    db = get_db()
    items = db.execute(
        """
        SELECT ci.id AS cart_id, ci.quantity, p.id AS product_id, p.merchant_id,
               p.name, p.price, p.stock, p.status
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE ci.user_id = ?
        ORDER BY ci.id
        """,
        (g.user["id"],),
    ).fetchall()
    if not items:
        flash("购物车为空。")
        return redirect(url_for("cart"))

    for item in items:
        if item["status"] != "active" or item["stock"] < item["quantity"]:
            flash(f"{item['name']} 库存不足或已下架。")
            return redirect(url_for("cart"))

    total = round(sum(item["price"] * item["quantity"] for item in items), 2)
    try:
        db.execute("BEGIN")
        cursor = db.execute(
            "INSERT INTO orders (user_id, total_amount, status) VALUES (?, ?, 'submitted')",
            (g.user["id"], total),
        )
        order_id = cursor.lastrowid
        for item in items:
            db.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name, price, quantity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (order_id, item["product_id"], item["name"], item["price"], item["quantity"]),
            )
            db.execute(
                "UPDATE products SET stock = stock - ?, sales = sales + ? WHERE id = ?",
                (item["quantity"], item["quantity"], item["product_id"]),
            )
        for merchant_id in {item["merchant_id"] for item in items}:
            db.execute(
                """
                INSERT INTO merchant_order_fulfillments (order_id, merchant_id, status)
                VALUES (?, ?, 'new')
                """,
                (order_id, merchant_id),
            )
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (g.user["id"],))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        flash("提交订单失败，请稍后重试。")
        return redirect(url_for("cart"))

    flash("订单提交成功。")
    return redirect(url_for("consumer_orders"))


@app.route("/orders")
@role_required("consumer")
def consumer_orders():
    db = get_db()
    orders = db.execute(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)
    ).fetchall()
    order_items = {}
    fulfillments = {}
    for order in orders:
        order_items[order["id"]] = db.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order["id"],)
        ).fetchall()
        fulfillments[order["id"]] = db.execute(
            """
            SELECT mof.*, u.display_name AS merchant_name
            FROM merchant_order_fulfillments mof
            JOIN users u ON u.id = mof.merchant_id
            WHERE mof.order_id = ?
            ORDER BY mof.id
            """,
            (order["id"],),
        ).fetchall()
    return render_template(
        "orders.html",
        orders=orders,
        order_items=order_items,
        fulfillments=fulfillments,
    )


@app.route("/merchant")
@role_required("merchant")
def merchant_dashboard():
    db = get_db()
    products = db.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        WHERE p.merchant_id = ?
        ORDER BY p.updated_at DESC
        """,
        (g.user["id"],),
    ).fetchall()
    applications = db.execute(
        """
        SELECT pa.*, c.name AS category_name
        FROM product_applications pa
        JOIN categories c ON c.id = pa.category_id
        WHERE pa.merchant_id = ?
        ORDER BY
            CASE pa.status WHEN 'pending' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,
            pa.submitted_at DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("merchant/dashboard.html", products=products, applications=applications)


@app.route("/merchant/orders")
@role_required("merchant")
def merchant_orders():
    db = get_db()
    fulfillments = db.execute(
        """
        SELECT mof.*, o.status AS order_status, o.created_at AS order_created_at,
               u.username, u.display_name,
               COALESCE(SUM(oi.price * oi.quantity), 0) AS merchant_total
        FROM merchant_order_fulfillments mof
        JOIN orders o ON o.id = mof.order_id
        JOIN users u ON u.id = o.user_id
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id AND p.merchant_id = mof.merchant_id
        WHERE mof.merchant_id = ?
        GROUP BY mof.id
        ORDER BY mof.created_at DESC, mof.id DESC
        """,
        (g.user["id"],),
    ).fetchall()
    fulfillment_items = {}
    for fulfillment in fulfillments:
        fulfillment_items[fulfillment["id"]] = db.execute(
            """
            SELECT oi.*
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ? AND p.merchant_id = ?
            ORDER BY oi.id
            """,
            (fulfillment["order_id"], g.user["id"]),
        ).fetchall()
    return render_template(
        "merchant/orders.html",
        fulfillments=fulfillments,
        fulfillment_items=fulfillment_items,
    )


@app.post("/merchant/orders/<int:fulfillment_id>/request-shipment")
@role_required("merchant")
def merchant_request_shipment(fulfillment_id):
    shipping_note = request.form.get("shipping_note", "").strip()
    if not shipping_note:
        flash("申请发货时请填写物流单号或配送说明。")
        return redirect(url_for("merchant_orders"))
    result = get_db().execute(
        """
        UPDATE merchant_order_fulfillments
        SET status = 'shipment_requested', shipping_note = ?, reject_reason = NULL,
            requested_at = CURRENT_TIMESTAMP, reviewed_by = NULL, reviewed_at = NULL
        WHERE id = ? AND merchant_id = ? AND status IN ('new', 'rejected')
          AND EXISTS (
              SELECT 1 FROM orders o
              WHERE o.id = merchant_order_fulfillments.order_id
                AND o.status NOT IN ('cancelled', 'completed')
          )
        """,
        (shipping_note, fulfillment_id, g.user["id"]),
    )
    get_db().commit()
    if result.rowcount:
        flash("发货申请已提交，等待管理员审批。")
    else:
        flash("当前订单不能重复申请发货。")
    return redirect(url_for("merchant_orders"))


@app.route("/merchant/applications/new", methods=("GET", "POST"))
@role_required("merchant")
def merchant_new_application():
    if request.method == "POST":
        data, error = parse_product_form(default_status="active")
        if error:
            flash(error)
        else:
            data["requested_status"] = "active"
            conflict = insert_application(g.user["id"], None, "create", data)
            if conflict:
                flash(conflict)
            else:
                flash("新增商品申请已提交，等待管理员审核。")
                return redirect(url_for("merchant_dashboard"))
    return render_template(
        "merchant/application_form.html",
        categories=fetch_categories(),
        application=None,
        product=None,
        mode="create",
    )


@app.route("/merchant/products/<int:product_id>/apply-edit", methods=("GET", "POST"))
@role_required("merchant")
def merchant_apply_edit(product_id):
    product = get_db().execute(
        "SELECT * FROM products WHERE id = ? AND merchant_id = ?", (product_id, g.user["id"])
    ).fetchone()
    if product is None:
        abort(404)
    if request.method == "POST":
        data, error = parse_product_form(default_status=product["status"])
        if error:
            flash(error)
        else:
            conflict = insert_application(g.user["id"], product_id, "update", data)
            if conflict:
                flash(conflict)
            else:
                flash("商品修改申请已提交，等待管理员审核。")
                return redirect(url_for("merchant_dashboard"))
    return render_template(
        "merchant/application_form.html",
        categories=fetch_categories(),
        application=None,
        product=product,
        mode="update",
    )


@app.post("/merchant/products/<int:product_id>/apply-status/<action>")
@role_required("merchant")
def merchant_apply_status(product_id, action):
    if action not in {"list", "delist"}:
        abort(404)
    product = get_db().execute(
        "SELECT * FROM products WHERE id = ? AND merchant_id = ?", (product_id, g.user["id"])
    ).fetchone()
    if product is None:
        abort(404)
    requested_status = "active" if action == "list" else "inactive"
    conflict = insert_application(
        g.user["id"],
        product_id,
        action,
        product_to_application_data(product, requested_status=requested_status),
    )
    flash(conflict or "上下架申请已提交，等待管理员审核。")
    return redirect(url_for("merchant_dashboard"))


@app.route("/merchant/applications/<int:application_id>/edit", methods=("GET", "POST"))
@role_required("merchant")
def merchant_edit_application(application_id):
    application = get_db().execute(
        """
        SELECT * FROM product_applications
        WHERE id = ? AND merchant_id = ? AND status = 'rejected'
        """,
        (application_id, g.user["id"]),
    ).fetchone()
    if application is None:
        abort(404)
    if request.method == "POST":
        data, error = parse_product_form(default_status=application["requested_status"])
        if error:
            flash(error)
        else:
            if application["product_id"] is None:
                conflict = get_db().execute(
                    """
                    SELECT id FROM products WHERE merchant_id = ? AND name = ?
                    UNION ALL
                    SELECT id FROM product_applications
                    WHERE merchant_id = ? AND product_id IS NULL AND name = ?
                      AND status = 'pending' AND id != ?
                    LIMIT 1
                    """,
                    (g.user["id"], data["name"], g.user["id"], data["name"], application_id),
                ).fetchone()
            else:
                conflict = get_db().execute(
                    """
                    SELECT id FROM product_applications
                    WHERE product_id = ? AND status = 'pending' AND id != ?
                    """,
                    (application["product_id"], application_id),
                ).fetchone()
            if conflict:
                flash("该商品已有正式记录或其他待审核申报，暂时不能重新提交。")
                return render_template(
                    "merchant/application_form.html",
                    categories=fetch_categories(),
                    application=application,
                    product=None,
                    mode="resubmit",
                )
            get_db().execute(
                """
                UPDATE product_applications
                SET name = ?, category_id = ?, origin = ?, price = ?, stock = ?, image_url = ?,
                    description = ?, requested_status = ?, status = 'pending',
                    reviewed_by = NULL, reviewed_at = NULL, submitted_at = CURRENT_TIMESTAMP
                WHERE id = ? AND merchant_id = ?
                """,
                (
                    data["name"],
                    data["category_id"],
                    data["origin"],
                    data["price"],
                    data["stock"],
                    data["image_url"],
                    data["description"],
                    data["requested_status"],
                    application_id,
                    g.user["id"],
                ),
            )
            get_db().commit()
            flash("申请已重新提交，等待管理员审核。")
            return redirect(url_for("merchant_dashboard"))
    return render_template(
        "merchant/application_form.html",
        categories=fetch_categories(),
        application=application,
        product=None,
        mode="resubmit",
    )


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    db = get_db()
    stats = {
        "product_count": db.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "active_count": db.execute("SELECT COUNT(*) FROM products WHERE status = 'active'").fetchone()[0],
        "pending_count": db.execute("SELECT COUNT(*) FROM product_applications WHERE status = 'pending'").fetchone()[0],
        "pending_shipment_count": db.execute(
            "SELECT COUNT(*) FROM merchant_order_fulfillments WHERE status = 'shipment_requested'"
        ).fetchone()[0],
        "low_stock_count": db.execute(
            "SELECT COUNT(*) FROM products WHERE stock <= ?", (LOW_STOCK_THRESHOLD,)
        ).fetchone()[0],
        "order_total": db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders").fetchone()[0],
    }
    top_products = db.execute(
        """
        SELECT name, sales
        FROM products
        ORDER BY sales DESC, id DESC
        LIMIT 8
        """
    ).fetchall()
    low_stock = db.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        WHERE p.stock <= ?
        ORDER BY p.stock ASC
        LIMIT 10
        """,
        (LOW_STOCK_THRESHOLD,),
    ).fetchall()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        top_products=top_products,
        low_stock=low_stock,
    )


@app.route("/admin/applications")
@role_required("admin")
def admin_applications():
    applications = get_db().execute(
        """
        SELECT pa.*, c.name AS category_name, u.display_name AS merchant_name, p.name AS current_product_name
        FROM product_applications pa
        JOIN categories c ON c.id = pa.category_id
        JOIN users u ON u.id = pa.merchant_id
        LEFT JOIN products p ON p.id = pa.product_id
        ORDER BY
            CASE pa.status WHEN 'pending' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,
            pa.submitted_at DESC
        """
    ).fetchall()
    return render_template("admin/applications.html", applications=applications)


@app.post("/admin/applications/<int:application_id>/approve")
@role_required("admin")
def approve_application(application_id):
    db = get_db()
    application = db.execute(
        "SELECT * FROM product_applications WHERE id = ?", (application_id,)
    ).fetchone()
    if application is None:
        abort(404)
    if application["status"] != "pending":
        flash("只能审核待处理申请。")
        return redirect(url_for("admin_applications"))
    if application["application_type"] == "create":
        duplicate = db.execute(
            "SELECT id FROM products WHERE merchant_id = ? AND name = ?",
            (application["merchant_id"], application["name"]),
        ).fetchone()
        if duplicate:
            flash("该商家已有同名正式商品，不能批准重复的新增产品申报。")
            return redirect(url_for("admin_applications"))

    try:
        db.execute("BEGIN")
        if application["application_type"] == "create":
            cursor = db.execute(
                """
                INSERT INTO products
                (merchant_id, category_id, name, origin, price, stock, image_url, description, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application["merchant_id"],
                    application["category_id"],
                    application["name"],
                    application["origin"],
                    application["price"],
                    application["stock"],
                    application["image_url"],
                    application["description"],
                    application["requested_status"],
                ),
            )
            product_id = cursor.lastrowid
        else:
            product_id = application["product_id"]
            if product_id is None:
                raise sqlite3.IntegrityError("application has no product")
            db.execute(
                """
                UPDATE products
                SET category_id = ?, name = ?, origin = ?, price = ?, stock = ?, image_url = ?,
                    description = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND merchant_id = ?
                """,
                (
                    application["category_id"],
                    application["name"],
                    application["origin"],
                    application["price"],
                    application["stock"],
                    application["image_url"],
                    application["description"],
                    application["requested_status"],
                    product_id,
                    application["merchant_id"],
                ),
            )
        db.execute(
            """
            UPDATE product_applications
            SET status = 'approved', product_id = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (product_id, g.user["id"], application_id),
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        flash("批准申请失败，请检查商品或分类是否仍然存在。")
        return redirect(url_for("admin_applications"))

    flash("申请已批准，商品数据已生效。")
    return redirect(url_for("admin_applications"))


@app.post("/admin/applications/<int:application_id>/reject")
@role_required("admin")
def reject_application(application_id):
    reason = request.form.get("reject_reason", "").strip()
    if not reason:
        flash("驳回申请必须填写理由。")
        return redirect(url_for("admin_applications"))
    result = get_db().execute(
        """
        UPDATE product_applications
        SET status = 'rejected', reject_reason = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'pending'
        """,
        (reason, g.user["id"], application_id),
    )
    get_db().commit()
    if result.rowcount == 0:
        flash("只能驳回待审核申请。")
    else:
        flash("申请已驳回，理由已发送给商家。")
    return redirect(url_for("admin_applications"))


@app.route("/admin/categories", methods=("GET", "POST"))
@role_required("admin")
def admin_categories():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        category_id = request.form.get("category_id")
        try:
            if action == "add":
                if not name:
                    flash("分类名称不能为空。")
                else:
                    db.execute("INSERT INTO categories (name, description) VALUES (?, ?)", (name, description))
                    db.commit()
                    flash("分类已新增。")
            elif action == "edit":
                db.execute(
                    "UPDATE categories SET name = ?, description = ? WHERE id = ?",
                    (name, description, category_id),
                )
                db.commit()
                flash("分类已修改。")
            elif action == "delete":
                used = db.execute(
                    "SELECT COUNT(*) FROM products WHERE category_id = ?", (category_id,)
                ).fetchone()[0]
                if used:
                    flash("该分类已有商品使用，不能删除。")
                else:
                    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
                    db.commit()
                    flash("分类已删除。")
        except sqlite3.IntegrityError:
            flash("分类名称已存在或仍被申请记录引用。")
        return redirect(url_for("admin_categories"))
    categories = db.execute(
        """
        SELECT c.*, COUNT(p.id) AS product_count
        FROM categories c
        LEFT JOIN products p ON p.category_id = c.id
        GROUP BY c.id
        ORDER BY c.name
        """
    ).fetchall()
    return render_template("admin/categories.html", categories=categories)


@app.route("/admin/products")
@role_required("admin")
def admin_products():
    products = get_db().execute(
        """
        SELECT p.*, c.name AS category_name, u.display_name AS merchant_name
        FROM products p
        JOIN categories c ON c.id = p.category_id
        JOIN users u ON u.id = p.merchant_id
        ORDER BY p.updated_at DESC
        """
    ).fetchall()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/<int:product_id>/edit", methods=("GET", "POST"))
@role_required("admin")
def admin_edit_product(product_id):
    product = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        abort(404)
    if request.method == "POST":
        data, error = parse_product_form(default_status=product["status"])
        if error:
            flash(error)
        else:
            try:
                get_db().execute(
                    """
                    UPDATE products
                    SET category_id = ?, name = ?, origin = ?, price = ?, stock = ?, image_url = ?,
                        description = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        data["category_id"],
                        data["name"],
                        data["origin"],
                        data["price"],
                        data["stock"],
                        data["image_url"],
                        data["description"],
                        data["requested_status"],
                        product_id,
                    ),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                get_db().rollback()
                flash("该商家已有同名商品，不能保存重复商品。")
            else:
                flash("商品已修改。")
                return redirect(url_for("admin_products"))
    return render_template(
        "merchant/application_form.html",
        categories=fetch_categories(),
        application=None,
        product=product,
        mode="admin_edit",
    )


@app.post("/admin/products/<int:product_id>/delete")
@role_required("admin")
def admin_delete_product(product_id):
    get_db().execute(
        "UPDATE products SET status = 'inactive', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (product_id,),
    )
    get_db().commit()
    flash("商品已下架。")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@role_required("admin")
def admin_orders():
    db = get_db()
    orders = db.execute(
        """
        SELECT o.*, u.username, u.display_name
        FROM orders o
        JOIN users u ON u.id = o.user_id
        ORDER BY o.created_at DESC
        """
    ).fetchall()
    order_items = {}
    fulfillments = {}
    for order in orders:
        order_items[order["id"]] = db.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order["id"],)
        ).fetchall()
        fulfillments[order["id"]] = db.execute(
            """
            SELECT mof.*, u.display_name AS merchant_name
            FROM merchant_order_fulfillments mof
            JOIN users u ON u.id = mof.merchant_id
            WHERE mof.order_id = ?
            ORDER BY mof.id
            """,
            (order["id"],),
        ).fetchall()
    return render_template(
        "admin/orders.html",
        orders=orders,
        order_items=order_items,
        fulfillments=fulfillments,
    )


@app.post("/admin/fulfillments/<int:fulfillment_id>/approve")
@role_required("admin")
def approve_shipment(fulfillment_id):
    db = get_db()
    fulfillment = db.execute(
        """
        SELECT mof.*
        FROM merchant_order_fulfillments mof
        JOIN orders o ON o.id = mof.order_id
        WHERE mof.id = ? AND mof.status = 'shipment_requested'
          AND o.status NOT IN ('cancelled', 'completed')
        """,
        (fulfillment_id,),
    ).fetchone()
    if fulfillment is None:
        flash("只能批准待审批的发货申请。")
        return redirect(url_for("admin_orders"))

    db.execute(
        """
        UPDATE merchant_order_fulfillments
        SET status = 'shipped', reject_reason = NULL, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (g.user["id"], fulfillment_id),
    )
    unfinished = db.execute(
        """
        SELECT COUNT(*) FROM merchant_order_fulfillments
        WHERE order_id = ? AND status != 'shipped'
        """,
        (fulfillment["order_id"],),
    ).fetchone()[0]
    if unfinished == 0:
        db.execute(
            "UPDATE orders SET status = 'shipped', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (fulfillment["order_id"],),
        )
    db.commit()
    flash("发货申请已批准。")
    return redirect(url_for("admin_orders"))


@app.post("/admin/fulfillments/<int:fulfillment_id>/reject")
@role_required("admin")
def reject_shipment(fulfillment_id):
    reason = request.form.get("reject_reason", "").strip()
    if not reason:
        flash("驳回发货申请必须填写理由。")
        return redirect(url_for("admin_orders"))
    result = get_db().execute(
        """
        UPDATE merchant_order_fulfillments
        SET status = 'rejected', reject_reason = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'shipment_requested'
        """,
        (reason, g.user["id"], fulfillment_id),
    )
    get_db().commit()
    flash("发货申请已驳回。" if result.rowcount else "只能驳回待审批的发货申请。")
    return redirect(url_for("admin_orders"))


@app.post("/admin/orders/<int:order_id>/status")
@role_required("admin")
def update_order_status(order_id):
    status = request.form.get("status")
    if status not in {"submitted", "paid", "shipped", "completed", "cancelled"}:
        flash("订单状态不正确。")
        return redirect(url_for("admin_orders"))
    if status == "shipped":
        unfinished = get_db().execute(
            """
            SELECT COUNT(*) FROM merchant_order_fulfillments
            WHERE order_id = ? AND status != 'shipped'
            """,
            (order_id,),
        ).fetchone()[0]
        if unfinished:
            flash("仍有商家发货申请未批准，不能直接把订单设为已发货。")
            return redirect(url_for("admin_orders"))
    get_db().execute(
        "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, order_id),
    )
    get_db().commit()
    flash("订单状态已更新。")
    return redirect(url_for("admin_orders"))


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    users = get_db().execute(
        """
        SELECT u.*,
               (SELECT COUNT(*) FROM products p WHERE p.merchant_id = u.id) AS product_count,
               (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) AS order_count
        FROM users u
        ORDER BY u.role, u.created_at DESC
        """
    ).fetchall()
    return render_template("admin/users.html", users=users)


if __name__ == "__main__":
    init_database()
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, host="127.0.0.1", port=port, use_reloader=False)
