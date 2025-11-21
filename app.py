from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import pandas as pd
import matplotlib.pyplot as plt
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from flask import jsonify

app = Flask(__name__)
app.secret_key = 'secretkey123'

# ---------------- DB CONNECTION ----------------
import os
import mysql.connector

def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        port=int(os.environ.get("DB_PORT"))
    )


# ---------------- LOGIN REQUIRED DECORATOR ----------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Login required", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ---------------- LOGIN PAGE ----------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))

# ---------------- DASHBOARD ----------------
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS product_count FROM products")
    product_count = cursor.fetchone()['product_count']

    cursor.execute("SELECT SUM(stock) AS total_stock FROM products")
    total_stock = cursor.fetchone()['total_stock'] or 0

    cursor.execute("SELECT SUM(total_amount) AS today_sales FROM sales WHERE DATE(sale_date)=CURDATE()")
    today_sales = cursor.fetchone()['today_sales'] or 0

    cursor.close()
    conn.close()
    return render_template('dashboard.html',
                           product_count=product_count,
                           total_stock=total_stock,
                           today_sales=today_sales)

@app.route('/dashboard/chart.png')
@login_required
def dashboard_chart():
    conn = get_db()
    sales_df = pd.read_sql("""
        SELECT DATE(sale_date) AS date, SUM(total_amount) as total
        FROM sales
        WHERE sale_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY DATE(sale_date)
        ORDER BY DATE(sale_date)
    """, con=conn)
    prod_df = pd.read_sql("""
        SELECT p.name, SUM(si.quantity) as qty
        FROM sale_items si JOIN products p ON si.product_id=p.id
        GROUP BY p.name ORDER BY qty DESC LIMIT 5
    """, con=conn)
    conn.close()

    plt.figure(figsize=(8, 4))
    plt.subplot(1, 2, 1)
    if not sales_df.empty:
        plt.plot(sales_df['date'], sales_df['total'], marker='o')
        plt.title('Last 7 Days Sales')
        plt.xticks(rotation=45)
    else:
        plt.text(0.5, 0.5, 'No Sales', ha='center', va='center')

    plt.subplot(1, 2, 2)
    if not prod_df.empty:
        plt.barh(prod_df['name'], prod_df['qty'])
        plt.title('Top 5 Products')
        plt.gca().invert_yaxis()
    else:
        plt.text(0.5, 0.5, 'No Data', ha='center', va='center')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/dashboard/data')
@login_required
def dashboard_data():
    conn = get_db()
    
    # Sales in last 7 days
    sales_df = pd.read_sql("""
        SELECT DATE(sale_date) AS date, SUM(total_amount) AS total
        FROM sales
        WHERE sale_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY DATE(sale_date)
        ORDER BY DATE(sale_date)
    """, con=conn)
    
    # Top 5 products
    prod_df = pd.read_sql("""
        SELECT p.name, SUM(si.quantity) AS qty
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        GROUP BY p.name
        ORDER BY qty DESC
        LIMIT 5
    """, con=conn)
    
    conn.close()

    return jsonify({
        "sales": {
            "labels": sales_df['date'].astype(str).tolist(),
            "data": sales_df['total'].tolist()
        },
        "top_products": {
            "labels": prod_df['name'].tolist(),
            "data": prod_df['qty'].tolist()
        }
    })

# ---------------- PRODUCTS MODULE ----------------
@app.route('/products')
@login_required
def products():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('products.html', products=products)

@app.route('/product/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        stock = request.form['stock']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO products (name, price, stock) VALUES (%s, %s, %s)", (name, price, stock))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Product added successfully!", "success")
        return redirect(url_for('products'))

    return render_template('product_form.html', action='Add')

@app.route('/product/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id=%s", (id,))
    product = cursor.fetchone()

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        stock = request.form['stock']

        cursor.execute("UPDATE products SET name=%s, price=%s, stock=%s WHERE id=%s", (name, price, stock, id))
        conn.commit()
        flash("Product updated!", "info")
        return redirect(url_for('products'))

    conn.close()
    return render_template('product_form.html', action='Edit', product=product)

@app.route('/product/delete/<int:id>')
@login_required
def delete_product(id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Check if product has any sales
        cursor.execute("SELECT COUNT(*) FROM sale_items WHERE product_id=%s", (id,))
        sale_count = cursor.fetchone()[0]

        if sale_count > 0:
            flash("Cannot delete product because it has associated sales.", "danger")
        else:
            cursor.execute("DELETE FROM products WHERE id=%s", (id,))
            conn.commit()
            flash("Product deleted successfully!", "success")
    except mysql.connector.Error as e:
        flash(f"Error deleting product: {e}", "danger")
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('products'))


# ---------------- SALES MODULE ----------------
@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        product_id = request.form['product_id']
        quantity = int(request.form['quantity'])

        cursor.execute("SELECT * FROM products WHERE id=%s", (product_id,))
        product = cursor.fetchone()

        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for('sales'))

        # Determine unit price from product record (supports 'price' or 'unit_price')
        if 'price' in product:
            unit_price = float(product['price'])
        elif 'unit_price' in product:
            unit_price = float(product['unit_price'])
        else:
            flash("Product price column not found.", "danger")
            return redirect(url_for('sales'))

        stock = int(product['stock'])

        if quantity > stock:
            flash("Not enough stock available!", "danger")
            return redirect(url_for('sales'))

        total_amount = quantity * unit_price

        cursor.execute("INSERT INTO sales (sale_date, total_amount) VALUES (NOW(), %s)", (total_amount,))
        sale_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO sale_items (sale_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (sale_id, product_id, quantity, unit_price))

        cursor.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (quantity, product_id))

        conn.commit()
        flash("Sale recorded successfully!", "success")
        return redirect(url_for('sales'))

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    cursor.execute("""
        SELECT s.id, s.sale_date, s.total_amount,
               p.name AS product_name, si.quantity, si.unit_price
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        JOIN products p ON si.product_id = p.id
        ORDER BY s.sale_date DESC
    """)
    sales_data = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('sales.html', products=products, sales_data=sales_data)



# ---------------- REPORTS ----------------
@app.route('/reports', methods=['GET'])
@login_required
def reports():
    # Use GET params, default to last 7 days
    start = request.args.get('start')
    end = request.args.get('end')
    
    if not start:
        start = (datetime.now() - pd.Timedelta(days=7)).date().isoformat()
    if not end:
        end = datetime.now().date().isoformat()

    # Fetch summary data
    conn = get_db()
    summary_df = pd.read_sql("""
        SELECT SUM(total_amount) AS total_sales, COUNT(*) AS transactions
        FROM sales
        WHERE DATE(sale_date) BETWEEN %s AND %s
    """, con=conn, params=(start, end))
    conn.close()

    summary = {
        "total_sales": float(summary_df['total_sales'].iloc[0] or 0),
        "transactions": int(summary_df['transactions'].iloc[0] or 0)
    }

    return render_template('reports.html', start=start, end=end, summary=summary)


@app.route('/reports/chart.png')
@login_required
def reports_chart():
    start = request.args.get('start')
    end = request.args.get('end')
    conn = get_db()
    df = pd.read_sql("""
        SELECT DATE(sale_date) AS sale_date, SUM(total_amount) as total
        FROM sales
        WHERE DATE(sale_date) BETWEEN %s AND %s
        GROUP BY DATE(sale_date)
        ORDER BY sale_date
    """, con=conn, params=(start or '2000-01-01', end or datetime.now().date()))
    conn.close()

    plt.figure(figsize=(6, 4))
    plt.plot(df['sale_date'], df['total'], marker='o')
    plt.title('Sales Report')
    plt.xticks(rotation=45)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/reports/export/<fmt>')
@login_required
def export_sales(fmt):
    start = request.args.get('start')
    end = request.args.get('end')
    conn = get_db()
    df = pd.read_sql("""
        SELECT DATE(sale_date) AS sale_date, SUM(total_amount) as total
        FROM sales
        WHERE DATE(sale_date) BETWEEN %s AND %s
        GROUP BY DATE(sale_date)
        ORDER BY sale_date
    """, con=conn, params=(start, end))
    conn.close()

    if fmt == 'csv':
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"sales_{start}_to_{end}.csv")

    elif fmt == 'pdf':
        buf = io.BytesIO()
        pdf = canvas.Canvas(buf, pagesize=letter)
        pdf.drawString(1 * inch, 10.5 * inch, f"Sales Report ({start} - {end})")
        y = 10 * inch
        pdf.setFont("Helvetica", 10)
        for _, row in df.iterrows():
            pdf.drawString(1 * inch, y, str(row['sale_date']))
            pdf.drawRightString(6.5 * inch, y, f"₱{row['total']:.2f}")
            y -= 0.3 * inch
        pdf.save()
        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=True,
                         download_name=f"sales_{start}_to_{end}.pdf")
    
@app.route('/reports/data')
@login_required
def reports_data():
    start = request.args.get('start')
    end = request.args.get('end')

    if not start or not end:
        return jsonify({"error": "Invalid date range"}), 400

    conn = get_db()
    df = pd.read_sql("""
        SELECT DATE(sale_date) AS date, SUM(total_amount) AS total
        FROM sales
        WHERE DATE(sale_date) BETWEEN %s AND %s
        GROUP BY DATE(sale_date)
        ORDER BY DATE(sale_date)
    """, con=conn, params=(start, end))
    conn.close()

    return jsonify({
        "labels": df['date'].astype(str).tolist(),
        "data": df['total'].tolist()
    })

    
    


# ---------------- CHANGE PASSWORD ----------------
@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_pw = request.form['old_password']
        new_pw = request.form['new_password']
        confirm_pw = request.form['confirm_password']

        if new_pw != confirm_pw:
            flash("New passwords do not match.", "danger")
            return redirect(url_for('change_password'))

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],))
        user = cursor.fetchone()

        if not user or not check_password_hash(user['password_hash'], old_pw):
            flash("Old password incorrect.", "danger")
        else:
            new_hash = generate_password_hash(new_pw)
            cursor.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, session['user_id']))
            conn.commit()
            flash("Password updated successfully!", "success")

        cursor.close()
        conn.close()
        return redirect(url_for('change_password'))

    return render_template('change_password.html')

if __name__ == '__main__':
    app.run(debug=True)
