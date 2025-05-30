from flask import Flask, request, redirect, render_template, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
import string
import random
import requests
import user_agents

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///grabify.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class URLMap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_url = db.Column(db.String(2048), nullable=False)
    short_id = db.Column(db.String(10), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    visits = db.relationship('Visit', backref='urlmap', lazy=True)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    urlmap_id = db.Column(db.Integer, db.ForeignKey('url_map.id'), nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    browser = db.Column(db.String(128))
    os = db.Column(db.String(128))
    referrer = db.Column(db.String(2048))
    country = db.Column(db.String(128))
    city = db.Column(db.String(128))
    screen_size = db.Column(db.String(64))
    color_scheme = db.Column(db.String(32))
    hdr_screen = db.Column(db.String(8))
    gpu = db.Column(db.String(256))
    platform = db.Column(db.String(64))
    timezone = db.Column(db.String(64))
    user_time = db.Column(db.String(64))
    language = db.Column(db.String(32))
    incognito = db.Column(db.String(8))
    ad_blocker = db.Column(db.String(8))
    orientation = db.Column(db.String(32))
    hostname = db.Column(db.String(256))
    isp = db.Column(db.String(256))
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())

# Helper functions
def generate_short_id(num_chars=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=num_chars))

def get_geolocation(ip):
    try:
        # Handle localhost IPs
        if ip == '127.0.0.1' or ip == '::1':
            return 'Localhost', 'Localhost'
        # Use ipapi.co with fields to ensure country_name and city are included
        response = requests.get(f'https://ipapi.co/{ip}/json/?fields=country_name,city')
        if response.status_code == 200:
            data = response.json()
            # Optional: log data for debugging
            # print(f"Geolocation data for IP {ip}: {data}")
            return data.get('country_name', ''), data.get('city', '')
    except Exception:
        pass
    return '', ''

def get_client_ip():
    # Prefer X-Forwarded-For header for real client IP (may contain multiple IPs)
    x_forwarded_for = request.headers.get('X-Forwarded-For', '')
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first public IP (IPv4 or IPv6)
        ips = [ip.strip() for ip in x_forwarded_for.split(',')]
        for ip in ips:
            # Skip private and localhost IPs
            if not (ip.startswith('10.') or ip.startswith('192.168.') or ip.startswith('172.') or ip == '127.0.0.1' or ip == '::1'):
                return ip
        # If no public IP found, fallback to first IP
        return ips[0]
    else:
        ip = request.remote_addr
    return ip

# Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        original_url = request.form.get('original_url')
        if not original_url:
            return render_template('index.html', error='Please enter a URL.')
        # Check if URL already shortened
        urlmap = URLMap.query.filter_by(original_url=original_url).first()
        if urlmap is None:
            short_id = generate_short_id()
            while URLMap.query.filter_by(short_id=short_id).first() is not None:
                short_id = generate_short_id()
            urlmap = URLMap(original_url=original_url, short_id=short_id)
            db.session.add(urlmap)
            db.session.commit()
        return render_template('index.html', short_url=url_for('track', short_id=urlmap.short_id, _external=True))
    return render_template('index.html')

@app.route('/track/<short_id>')
def track(short_id):
    urlmap = URLMap.query.filter_by(short_id=short_id).first_or_404()
    ip = get_client_ip()
    ua_string = request.headers.get('User-Agent', '')
    ua = user_agents.parse(ua_string)
    country, city = get_geolocation(ip)
    # Create visit with basic info first
    visit = Visit(
        urlmap_id=urlmap.id,
        ip_address=ip,
        user_agent=ua_string,
        browser=f"{ua.browser.family} {ua.browser.version_string}",
        os=f"{ua.os.family} {ua.os.version_string}",
        referrer=request.referrer or '',
        country=country,
        city=city
    )
    db.session.add(visit)
    db.session.commit()
    # Serve a tracking page with JS to collect advanced info and send to backend
    return render_template('track.html', short_id=short_id)

@app.route('/track_data/<short_id>', methods=['POST'])
def track_data(short_id):
    urlmap = URLMap.query.filter_by(short_id=short_id).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Find the latest visit for this URL and update with advanced data
    visit = Visit.query.filter_by(urlmap_id=urlmap.id).order_by(Visit.timestamp.desc()).first()
    if not visit:
        return jsonify({'error': 'No visit found to update'}), 404

    visit.screen_size = data.get('screen_size')
    visit.color_scheme = data.get('color_scheme')
    visit.hdr_screen = data.get('hdr_screen')
    visit.gpu = data.get('gpu')
    visit.platform = data.get('platform')
    visit.timezone = data.get('timezone')
    visit.user_time = data.get('user_time')
    visit.language = data.get('language')
    visit.incognito = data.get('incognito')
    visit.ad_blocker = data.get('ad_blocker')
    visit.orientation = data.get('orientation')

    # Update city and country if missing or empty
    if not visit.city or not visit.country:
        try:
            ip = visit.ip_address
            if ip and ip != '127.0.0.1' and ip != '::1':
                response = requests.get(f'https://ipapi.co/{ip}/json/?fields=country_name,city')
                if response.status_code == 200:
                    ip_data = response.json()
                    visit.country = ip_data.get('country_name', visit.country)
                    visit.city = ip_data.get('city', visit.city)
        except Exception:
            pass

    # Optionally, fetch hostname and ISP from IP using external API
    try:
        ip = visit.ip_address
        if ip and ip != '127.0.0.1' and ip != '::1':
            response = requests.get(f'https://ipapi.co/{ip}/json/?fields=org,hostname')
            if response.status_code == 200:
                ip_data = response.json()
                visit.isp = ip_data.get('org')
                visit.hostname = ip_data.get('hostname')
    except Exception:
        pass

    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/track_redirect/<short_id>')
def track_redirect(short_id):
    urlmap = URLMap.query.filter_by(short_id=short_id).first_or_404()
    return redirect(urlmap.original_url)

@app.route('/stats/<short_id>')
def stats(short_id):
    urlmap = URLMap.query.filter_by(short_id=short_id).first_or_404()
    visits = Visit.query.filter_by(urlmap_id=urlmap.id).order_by(Visit.timestamp.desc()).all()
    return render_template('stats.html', urlmap=urlmap, visits=visits)

@app.route('/pixel/<short_id>.png')
def pixel(short_id):
    urlmap = URLMap.query.filter_by(short_id=short_id).first_or_404()
    ip = get_client_ip()
    ua_string = request.headers.get('User-Agent', '')
    ua = user_agents.parse(ua_string)
    country, city = get_geolocation(ip)
    visit = Visit(
        urlmap_id=urlmap.id,
        ip_address=ip,
        user_agent=ua_string,
        browser=f"{ua.browser.family} {ua.browser.version_string}",
        os=f"{ua.os.family} {ua.os.version_string}",
        referrer=request.referrer or '',
        country=country,
        city=city
    )
    db.session.add(visit)
    db.session.commit()
    # Return a 1x1 transparent PNG
    pixel_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01' \
                 b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89' \
                 b'\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01' \
                 b'\xe2!\xbc\x33\x00\x00\x00\x00IEND\xaeB`\x82'
    return app.response_class(pixel_data, mimetype='image/png')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
