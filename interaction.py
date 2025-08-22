from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, flash
import pandas as pd
import os
import hashlib
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key')  # Secure key for production

# Define paths for Render
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
catalog_file = os.path.join(BASE_DIR, "cleaned_products1.csv")
interaction_file = os.path.join(BASE_DIR, "interactions.csv")

# Load the catalog CSV at startup
try:
    product_catalog = pd.read_csv(catalog_file)
    required_columns = ['id', 'title', 'brand', 'color', 'category', 'sub_category', 'material', 'occasion', 'preprocessed_product_details']
    if not all(col in product_catalog.columns for col in required_columns):
        raise ValueError("CSV missing required columns")
    # Clean up empty column from extra comma in CSV header
    if '' in product_catalog.columns:
        product_catalog.drop(columns=[''], inplace=True)
except FileNotFoundError:
    print(f"Error: {catalog_file} not found. Ensure the file is in the same directory.")
    exit(1)
except Exception as e:
    print(f"Error loading CSV: {e}")
    exit(1)

# Get unique categories and sub-categories
unique_categories = sorted(product_catalog['category'].dropna().unique().tolist())
sub_categories = product_catalog.groupby('category')['sub_category'].apply(lambda x: sorted(x.dropna().unique().tolist())).to_dict()

# Initialize interaction CSV with headers if it doesn't exist
if not os.path.exists(interaction_file):
    pd.DataFrame(columns=["user_id", "product_id", "click", "like", "dislike", "cart", "buy"]).to_csv(interaction_file, index=False)

# Serve images from the /images folder
@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'images'), filename)

# Function to generate user_id from IP address or session
def generate_user_id():
    # Try to get client IP from X-Forwarded-For header
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    # X-Forwarded-For may contain multiple IPs; take the first (client IP)
    if ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()
    
    # If IP is invalid or a proxy IP (e.g., 172.x.x.x), use a random session ID
    if not ip_address or ip_address.startswith(('10.', '172.', '192.168.')):
        if 'random_user_id' not in session:
            session['random_user_id'] = str(uuid.uuid4())
        return hashlib.sha256(session['random_user_id'].encode('utf-8')).hexdigest()
    
    return hashlib.sha256(ip_address.encode('utf-8')).hexdigest()

# Function to log interaction
def log_interaction(user_id, product_id, click=0, like=0, dislike=0, cart=0, buy=0):
    try:
        interactions = pd.read_csv(interaction_file)
    except pd.errors.EmptyDataError:
        interactions = pd.DataFrame(columns=["user_id", "product_id", "click", "like", "dislike", "cart", "buy"])

    mask = (interactions['user_id'] == user_id) & (interactions['product_id'] == product_id)
    if mask.any():
        interactions.loc[mask, 'click'] = interactions.loc[mask, 'click'] | click
        interactions.loc[mask, 'like'] = interactions.loc[mask, 'like'] | like
        interactions.loc[mask, 'dislike'] = interactions.loc[mask, 'dislike'] | dislike
        interactions.loc[mask, 'cart'] = interactions.loc[mask, 'cart'] | cart
        interactions.loc[mask, 'buy'] = interactions.loc[mask, 'buy'] | buy
    else:
        new_interaction = {
            "user_id": user_id,
            "product_id": product_id,
            "click": click,
            "like": like,
            "dislike": dislike,
            "cart": cart,
            "buy": buy
        }
        interactions = pd.concat([interactions, pd.DataFrame([new_interaction])], ignore_index=True)
    
    interactions.to_csv(interaction_file, index=False)

# Route for root, auto-assign user_id based on IP or session
@app.route('/')
def index():
    session['user_id'] = generate_user_id()
    return redirect(url_for('catalog'))

# Route to display catalog with pagination, randomization, and category filters
@app.route('/catalog')
@app.route('/catalog/<int:page>')
def catalog(page=1):
    if 'user_id' not in session:
        session['user_id'] = generate_user_id()
    
    # Get selected category and sub_category from query parameters
    selected_category = request.args.get('category', '')
    selected_sub_category = request.args.get('sub_category', '')
    
    # Filter products based on selected category and sub_category
    filtered_products = product_catalog
    if selected_category:
        filtered_products = filtered_products[filtered_products['category'] == selected_category]
    if selected_sub_category:
        filtered_products = filtered_products[filtered_products['sub_category'] == selected_sub_category]
    
    # Randomize the filtered products
    filtered_products = filtered_products.sample(frac=1, random_state=None).reset_index(drop=True)
    
    # Pagination settings
    per_page = 30
    total_products = len(filtered_products)
    total_pages = (total_products + per_page - 1) // per_page
    
    # Ensure page is within valid range
    page = max(1, min(page, total_pages))
    
    # Get products for the current page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    products = filtered_products.iloc[start_idx:end_idx].to_dict(orient='records')
    
    # Add image path to each product
    for product in products:
        product['image_path'] = f"/images/{product['id']}.jpg"
    
    return render_template('catalog.html', products=products, page=page, total_pages=total_pages,
                           categories=unique_categories, sub_categories=sub_categories,
                           selected_category=selected_category, selected_sub_category=selected_sub_category)

# Route for product details and interactions
@app.route('/product/<int:product_id>', methods=['GET', 'POST'])
def product(product_id):
    if 'user_id' not in session:
        session['user_id'] = generate_user_id()
    
    # Find the product
    product = product_catalog[product_catalog['id'] == product_id].to_dict(orient='records')
    if not product:
        return "Product not found", 404
    product = product[0]
    product['image_path'] = f"/images/{product_id}.jpg"
    
    # Log click when viewing details
    log_interaction(session['user_id'], product_id, click=1)
    
    if request.method == 'POST':
        action = request.form.get('action')
        like, dislike, cart, buy = 0, 0, 0, 0
        if action == 'like':
            like = 1
        elif action == 'dislike':
            dislike = 1
        elif action == 'cart':
            cart = 1
        elif action == 'buy':
            buy = 1
            cart = 1
        log_interaction(session['user_id'], product_id, like=like, dislike=dislike, cart=cart, buy=buy)
        flash(f"{action.capitalize()} logged successfully!", "success")
        return render_template('product.html', product=product)
    
    return render_template('product.html', product=product)

# Route to logout/change user
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('random_user_id', None)  # Clear random ID if used
    return redirect(url_for('index'))

# Route to download interactions.csv with password protection
@app.route('/download_interactions', methods=['GET', 'POST'])
def download_interactions():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'sandy1234':
            try:
                return send_file(interaction_file, as_attachment=True, download_name='interactions.csv')
            except FileNotFoundError:
                flash('Error: interactions.csv not found.', 'error')
                return render_template('download.html')
        else:
            flash('Incorrect password.', 'error')
            return render_template('download.html')
    return render_template('download.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))