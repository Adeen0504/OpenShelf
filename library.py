from flask import Flask, render_template, redirect, request, url_for, session, flash, make_response, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
load_dotenv()
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'openshelf-dev-key')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
ADMIN_URL_TOKEN = os.environ.get('ADMIN_URL_TOKEN', 'secret-admin-panel')


# Database configuration
app.config['SQLALCHEMY_BINDS'] = {
    'auth':     'sqlite:///auth.db',
    'personal': 'sqlite:///user_data.db',
    'global':   'sqlite:///books.db'
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Inject admin token into all templates
@app.context_processor
def inject_admin_token():
    return {"ADMIN_URL_TOKEN": ADMIN_URL_TOKEN}


# ─────────────────────────── Models ───────────────────────────

class Account(db.Model):
    __bind_key__ = 'auth'
    __tablename__ = 'accounts'
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(100), unique=True, nullable=False)
    password  = db.Column(db.String(255), nullable=False)
    name      = db.Column(db.String(100), nullable=False)
    email     = db.Column(db.String(100), nullable=False)
    phone     = db.Column(db.String(15),  nullable=False)
    gender    = db.Column(db.String(10),  nullable=False)
    languages = db.Column(db.String(100), nullable=False)


class TextbookHistory(db.Model):
    __bind_key__ = 'personal'
    __tablename__ = 'textbook_history'
    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(50),  nullable=False)
    title          = db.Column(db.String(255),  nullable=False)
    author         = db.Column(db.String(255))
    image          = db.Column(db.String(255))
    reference_link = db.Column(db.String(500))
    date           = db.Column(db.String(50))
    action         = db.Column(db.String(20))


class SavedTextbook(db.Model):
    __bind_key__ = 'personal'
    __tablename__ = 'saved_textbooks'
    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(50),  nullable=False)
    title          = db.Column(db.String(255),  nullable=False)
    author         = db.Column(db.String(255))
    image          = db.Column(db.String(255))
    reference_link = db.Column(db.String(500))
    saved_date     = db.Column(db.String(50))


class GlobalBook(db.Model):
    __bind_key__ = 'global'
    __tablename__ = 'books'
    sno            = db.Column(db.Integer, primary_key=True)
    book_name      = db.Column(db.String(200))
    author_name    = db.Column(db.String(200))
    reference_link = db.Column(db.String(500))   # direct Gutenberg PDF URL
    image          = db.Column(db.String(500))
    note           = db.Column(db.String(255))


# ─────────────────────────── Public routes ───────────────────────────

@app.route('/', methods=['GET'])
def first():
    query = request.args.get('q', '').strip()
    if query:
        books = GlobalBook.query.filter(
            (GlobalBook.book_name.ilike(f'%{query}%')) |
            (GlobalBook.author_name.ilike(f'%{query}%'))
        ).limit(9).all()
    else:
        books = GlobalBook.query.limit(9).all()
    return render_template('first.html', books=books, query=query)


@app.route('/read/<int:book_id>')
def read_book(book_id):
    """Proxy-embed a Gutenberg PDF directly in the browser (no redirect)."""
    book = GlobalBook.query.get_or_404(book_id)

    # Track history if logged in
    if 'loggedin' in session:
        username = session['username']
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exists = TextbookHistory.query.filter_by(
            username=username, title=book.book_name, action='read'
        ).first()
        if not exists:
            entry = TextbookHistory(
                username=username, title=book.book_name,
                author=book.author_name, image=book.image,
                reference_link=book.reference_link,
                action='read', date=now
            )
            db.session.add(entry)
            db.session.commit()

    return render_template('read.html', book=book)


@app.route('/pdf-proxy/<int:book_id>')
def pdf_proxy(book_id):
    """Stream the Gutenberg PDF through our server so it embeds cleanly."""
    book = GlobalBook.query.get_or_404(book_id)
    try:
        r = requests.get(book.reference_link, stream=True, timeout=15)
        headers = {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'inline; filename="{book.book_name}.pdf"',
        }
        return Response(r.iter_content(chunk_size=8192), headers=headers)
    except Exception:
        return "Could not load PDF.", 502


# ─────────────────────────── Auth routes ───────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        name      = request.form['name']
        email     = request.form['email']
        phone     = request.form['phone']
        username  = request.form['username']
        password  = request.form['password']
        gender    = request.form['radio']
        languages = request.form.getlist('checkbox')

        if Account.query.filter_by(username=username).first():
            msg = 'Username already taken!'
        else:
            new_user = Account(
                name=name, email=email, phone=phone,
                username=username,
                password=generate_password_hash(password),
                gender=gender,
                languages=','.join(languages)
            )
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please log in.')
            return redirect(url_for('login'))
    return render_template('register.html', msg=msg)


@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = request.form.get('remember')

        account = Account.query.filter_by(username=username).first()
        if account and check_password_hash(account.password, password):
            session['loggedin'] = True
            session['username'] = account.username
            flash(f'Welcome back, {account.name}!')
            resp = make_response(redirect(url_for('home')))
            if remember == 'yes':
                resp.set_cookie('remembered_username', username, max_age=60*60*24*30)
            else:
                resp.set_cookie('remembered_username', '', expires=0)
            return resp
        else:
            msg = 'Incorrect username or password.'
    return render_template('login.html', msg=msg)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('first'))


# ─────────────────────────── Logged-in routes ───────────────────────────

@app.route('/home', methods=['GET', 'POST'])
def home():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        username       = session['username']
        title          = request.form.get('title')
        author_name    = request.form.get('author')
        image          = request.form.get('image')
        reference_link = request.form.get('reference_link')
        action         = request.form.get('action')
        now            = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == 'save':
            exists = SavedTextbook.query.filter_by(username=username, title=title).first()
            if not exists:
                new = SavedTextbook(
                    username=username, title=title,
                    author=author_name, image=image,
                    reference_link=reference_link, saved_date=now
                )
                db.session.add(new)
                db.session.commit()
                flash('Book saved!')
        return redirect(url_for('home'))

    query = request.args.get('q', '').strip()
    if query:
        books = GlobalBook.query.filter(
            (GlobalBook.book_name.ilike(f'%{query}%')) |
            (GlobalBook.author_name.ilike(f'%{query}%'))
        ).all()
    else:
        books = GlobalBook.query.all()

    return render_template('home.html', books=books, query=query)


@app.route('/profile')
def profile():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    username = session['username']
    user     = Account.query.filter_by(username=username).first()
    history  = TextbookHistory.query.filter_by(username=username).all()
    saved    = SavedTextbook.query.filter_by(username=username).all()

    history_sorted = sorted(
        history,
        key=lambda x: datetime.strptime(x.date, '%Y-%m-%d %H:%M:%S'),
        reverse=True
    )[:6]

    saved_sorted = sorted(
        saved,
        key=lambda x: datetime.strptime(x.saved_date, '%Y-%m-%d %H:%M:%S'),
        reverse=True
    )[:6]

    # Enrich with images from global DB if missing
    for item in history_sorted + saved_sorted:
        if not item.image:
            match = GlobalBook.query.filter_by(book_name=item.title).first()
            item.image = match.image if match else None

    return render_template('profile.html', user=user,
                           history=history_sorted, saved=saved_sorted)


@app.route('/remove_saved', methods=['POST'])
def remove_saved():
    if 'loggedin' in session:
        saved_id = request.form.get('saved_id')
        entry = SavedTextbook.query.get(saved_id)
        if entry and entry.username == session['username']:
            db.session.delete(entry)
            db.session.commit()
    return redirect(url_for('profile'))


# ─────────────────────────── Admin routes ───────────────────────────

@app.route(f'/{ADMIN_URL_TOKEN}', methods=['GET', 'POST'])
def admin_panel():
    """Hidden admin page — URL known only to you."""
    error = ''

    # If not authenticated as admin yet, show password gate
    if not session.get('admin_auth'):
        if request.method == 'POST' and request.form.get('admin_pw'):
            if request.form['admin_pw'] == ADMIN_PASSWORD:
                session['admin_auth'] = True
                return redirect(request.url)
            else:
                error = 'Wrong password.'
        return render_template('admin_login.html', error=error)

    # Authenticated — show full admin panel
    books      = GlobalBook.query.all()
    user_count = Account.query.count()
    return render_template('admin.html', books=books, user_count=user_count)


@app.route(f'/{ADMIN_URL_TOKEN}/add', methods=['POST'])
def admin_add_book():
    if not session.get('admin_auth'):
        return redirect(url_for('first'))

    total = GlobalBook.query.count()
    if total >= 100:
        flash('Library is full (100 books max). Delete a book first.')
        return redirect(f'/{ADMIN_URL_TOKEN}')

    book = GlobalBook(
        book_name      = request.form['book_name'],
        author_name    = request.form['author_name'],
        reference_link = request.form['reference_link'],
        image          = request.form['image'],
        note           = request.form.get('note', '')
    )
    db.session.add(book)
    db.session.commit()
    flash('Book added!')
    return redirect(f'/{ADMIN_URL_TOKEN}')


@app.route(f'/{ADMIN_URL_TOKEN}/delete/<int:book_id>', methods=['POST'])
def admin_delete_book(book_id):
    if not session.get('admin_auth'):
        return redirect(url_for('first'))
    book = GlobalBook.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash('Book deleted.')
    return redirect(f'/{ADMIN_URL_TOKEN}')


@app.route(f'/{ADMIN_URL_TOKEN}/logout')
def admin_logout():
    session.pop('admin_auth', None)
    return redirect(url_for('first'))


# ─────────────────────────── Run ───────────────────────────

if __name__ == "__main__":
    with app.app_context():
        Account.metadata.create_all(bind=db.engines['auth'])
        SavedTextbook.metadata.create_all(bind=db.engines['personal'])
        TextbookHistory.metadata.create_all(bind=db.engines['personal'])
        GlobalBook.metadata.create_all(bind=db.engines['global'])
    app.run(debug=True)
