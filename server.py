"""Flask server for Hikaya Store Admin Panel - God Mode Manager"""
import os, requests, json, sys, shutil
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='.')

APPWRITE_BASE = os.environ.get('APPWRITE_BASE', 'https://cloud.appwrite.io')
APPWRITE_ENDPOINT = f'{APPWRITE_BASE}/v1'

# Strip trailing /v1 or / if env var accidentally includes them
APPWRITE_BASE = APPWRITE_BASE.rstrip('/')
if APPWRITE_BASE.endswith('/v1'):
    APPWRITE_BASE = APPWRITE_BASE[:-3]
APPWRITE_PROJECT = os.environ.get('APPWRITE_PROJECT', '6a10ffc6002688e9bfb2')
APPWRITE_KEY = os.environ.get('APPWRITE_KEY', 'standard_4a7169cbb118359f7a269af914bc309ca9c9acf248101be7cdd520abfeebe2e390af35567de33c48a21aa318b79e8fc0a1b84d343ef3ba52d34842382fc2fe7bfb61b46e3170d94fcbda08524a7f9a12fc31438fb7a2961273668137485078d545d345e6c724ffcc4c594c789dee70e33565f545a29b6c37d1761d24d8727285')
BUCKET_ID = 'products'
DATABASE_ID = 'hikaya_store'
FCM_SERVER_KEY = os.environ.get('FCM_SERVER_KEY', '')

HEADERS = {
    'X-Appwrite-Project': APPWRITE_PROJECT,
    'X-Appwrite-Key': APPWRITE_KEY,
    'X-Appwrite-Response-Format': '1.5.0',
}

def aw(method, path, **kw):
    url = f'{APPWRITE_BASE}{path}'
    params = kw.pop('params', {})
    if 'project' not in params:
        params['project'] = APPWRITE_PROJECT
    h = {**HEADERS}
    if 'headers' in kw: h.update(kw.pop('headers'))
    is_json = kw.pop('_json', False)
    if is_json: h['Content-Type'] = 'application/json'
    r = requests.request(method, url, headers=h, params=params, **kw)
    return r

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/v1/<path:subpath>', methods=['GET','POST','PUT','PATCH','DELETE'])
def proxy(subpath):
    path = '/v1/' + subpath
    params = request.args.to_dict()
    ct = (request.content_type or '')
    if 'multipart' in ct:
        r = aw(request.method, path, params=params, data=request.form, files=request.files)
    elif request.is_json:
        r = aw(request.method, path, params=params, _json=True, json=request.json)
    else:
        r = aw(request.method, path, params=params, data=request.data)
    try:
        return jsonify(r.json()), r.status_code
    except:
        return r.text, r.status_code, {'Content-Type': r.headers.get('Content-Type','text/plain')}

@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    url = f'{APPWRITE_BASE}/v1/storage/buckets/{BUCKET_ID}/files'
    h = {**HEADERS}
    data = {'fileId': 'unique()'}
    r = requests.post(url, headers=h, params={'project': APPWRITE_PROJECT}, data=data,
                      files={'file': (f.filename, f.stream, f.content_type)})
    if not r.ok:
        return jsonify({'error': r.text}), r.status_code
    j = r.json()
    return jsonify({'fileId': j['$id'], 'url': f'{APPWRITE_BASE}/v1/storage/buckets/{BUCKET_ID}/files/{j["$id"]}/view?project={APPWRITE_PROJECT}'})

@app.route('/api/debug')
def debug():
    import traceback
    lines = []
    try:
        url = f'{APPWRITE_BASE}/v1/databases/{DATABASE_ID}/collections/settings'
        params = {'project': APPWRITE_PROJECT}
        h = {**HEADERS}
        lines.append(f'URL: {url}')
        lines.append(f'Headers: {dict(h)}')
        lines.append(f'Params: {params}')
        import socket
        lines.append(f'DNS: {socket.gethostbyname("cloud.appwrite.io")}')
        r = requests.get(url, headers=h, params=params, timeout=10)
        lines.append(f'Status: {r.status_code}')
        lines.append(f'Response: {r.text[:500]}')
    except Exception as e:
        lines.append(f'Error: {e}')
        lines.append(traceback.format_exc())
    return jsonify({'debug': lines})

@app.route('/api/dashboard')
def dashboard():
    try:
        prod = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/products/documents')
        ords = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/orders/documents')
        cats = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/categories/documents')
        products = prod.json().get('documents', [])
        orders = ords.json().get('documents', [])
        categories = cats.json().get('documents', [])
        total_revenue = sum(o.get('total', 0) for o in orders if o.get('status') == 'تم التوصيل')
        pending = sum(1 for o in orders if o.get('status') == 'قيد المعالجة')
        delivering = sum(1 for o in orders if o.get('status') == 'قيد التوصيل')
        delivered = sum(1 for o in orders if o.get('status') == 'تم التوصيل')
        cancelled = sum(1 for o in orders if o.get('status') == 'ملغي')
        return jsonify({
            'totalProducts': len(products),
            'totalOrders': len(orders),
            'totalCategories': len(categories),
            'totalRevenue': total_revenue,
            'pendingOrders': pending,
            'deliveringOrders': delivering,
            'deliveredOrders': delivered,
            'cancelledOrders': cancelled,
            'recentOrders': sorted(orders, key=lambda o: o.get('date', ''), reverse=True)[:5],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def send_fcm_notification(token, title, body):
    if not FCM_SERVER_KEY or not token:
        return
    try:
        msg = {
            'to': token,
            'notification': {'title': title, 'body': body, 'sound': 'default'},
            'android': {'priority': 'high', 'notification': {'channelId': 'hikaya_orders', 'priority': 'high'}},
        }
        requests.post('https://fcm.googleapis.com/fcm/send',
            headers={'Authorization': f'key={FCM_SERVER_KEY}', 'Content-Type': 'application/json'},
            json=msg, timeout=10)
    except Exception as e:
        print(f'FCM send error: {e}')

@app.route('/api/fcm/register', methods=['POST'])
def register_fcm():
    data = request.get_json(force=True)
    token = data.get('token', '')
    if not token:
        return jsonify({'error': 'Token required'}), 400
    tokens = _load_fcm_tokens()
    if token not in tokens:
        tokens.append(token)
        _save_fcm_tokens(tokens)
    return jsonify({'ok': True, 'count': len(tokens)})

@app.route('/api/fcm/tokens')
def get_fcm_tokens():
    return jsonify({'tokens': _load_fcm_tokens(), 'count': len(_load_fcm_tokens())})

@app.route('/api/fcm/test', methods=['POST'])
def test_fcm():
    data = request.get_json(force=True)
    token = data.get('token', '')
    if not token:
        return jsonify({'error': 'Token required'}), 400
    send_fcm_notification(token, '🔔 اختبار الإشعارات', 'هذا إشعار تجريبي من لوحة التحكم')
    return jsonify({'ok': True})

def _load_fcm_tokens():
    p = os.path.join(os.path.dirname(__file__), 'fcm_tokens.json')
    if os.path.exists(p):
        with open(p) as f: return json.load(f)
    return []

def _save_fcm_tokens(tokens):
    p = os.path.join(os.path.dirname(__file__), 'fcm_tokens.json')
    with open(p, 'w') as f: json.dump(tokens, f)

@app.route('/api/fcm/send-all', methods=['POST'])
def fcm_send_all():
    data = request.get_json(force=True)
    title = data.get('title', 'إشعار')
    body = data.get('body', '')
    tokens = _load_fcm_tokens()
    for token in tokens:
        send_fcm_notification(token, title, body)
    return jsonify({'ok': True, 'sent': len(tokens)})

@app.route('/api/orders/<order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    data = request.get_json(force=True)
    new_status = data.get('status', '')
    # Try direct PATCH by document ID first
    r = aw('PATCH', f'/v1/databases/{DATABASE_ID}/collections/orders/documents/{order_id}',
           _json=True, json={'data': {'status': new_status}})
    if not r.ok:
        # Fallback: find document by custom 'id' attribute
        search = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/orders/documents',
                    params={'queries[0]': f'equal("id","{order_id}")'})
        docs = (search.json() or {}).get('documents', [])
        if docs:
            real_id = docs[0].get('$id', '')
            r = aw('PATCH', f'/v1/databases/{DATABASE_ID}/collections/orders/documents/{real_id}',
                   _json=True, json={'data': {'status': new_status}})
    if not r.ok:
        return jsonify({'error': r.text}), r.status_code
    fcm_tokens = data.get('fcmTokens', [])
    if not isinstance(fcm_tokens, list) or len(fcm_tokens) == 0:
        fcm_tokens = _load_fcm_tokens()
    for token in fcm_tokens:
        send_fcm_notification(token, 'تحديث الطلب',
            f'تم تحديث حالة الطلب {order_id} إلى: {new_status}')
    return jsonify(r.json())

@app.route('/api/analytics')
def analytics():
    try:
        ords = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/orders/documents')
        orders = ords.json().get('documents', [])

        item_counts = {}
        daily_orders = {}
        daily_revenue = {}
        customers = set()

        for o in orders:
            date = o.get('date', '')[:10]
            customers.add(o.get('phone', ''))
            if date:
                daily_orders[date] = daily_orders.get(date, 0) + 1
                if o.get('status') == 'تم التوصيل':
                    daily_revenue[date] = daily_revenue.get(date, 0) + o.get('total', 0)
            items_raw = o.get('items', '[]')
            try:
                items = json.loads(items_raw) if isinstance(items_raw, str) else items_raw
            except:
                items = []
            for item in items:
                name = item.get('name', 'غير معروف')
                qty = item.get('quantity', 1)
                item_counts[name] = item_counts.get(name, 0) + qty

        popular = sorted(item_counts.items(), key=lambda x: -x[1])[:10]
        trends = sorted(daily_orders.items())
        rev_trends = sorted(daily_revenue.items())

        return jsonify({
            'totalCustomers': len(customers),
            'popularProducts': [{'name': n, 'count': c} for n, c in popular],
            'orderTrends': [{'date': d, 'count': c} for d, c in trends[-30:]],
            'revenueTrends': [{'date': d, 'total': t} for d, t in rev_trends[-30:]],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/orders/sync', methods=['POST'])
def sync_orders():
    """Ensure all orders in Appwrite have required attributes and clean up orphaned data."""
    ensure_order_attrs()
    return jsonify({'ok': True, 'message': 'Orders synced'})

@app.route('/api/bulk/<action>', methods=['POST'])
def bulk_action(action):
    data = request.get_json(force=True)
    ids = data.get('ids', [])
    field = data.get('field', '')
    value = data.get('value', '')
    errors = 0
    for doc_id in ids:
        if action == 'delete':
            r = aw('DELETE', f'/v1/databases/{DATABASE_ID}/collections/{data.get("collection", "products")}/documents/{doc_id}')
        elif action == 'update':
            body = {'data': {field: value}}
            r = aw('PATCH', f'/v1/databases/{DATABASE_ID}/collections/{data.get("collection", "products")}/documents/{doc_id}',
                   _json=True, json=body)
        else:
            return jsonify({'error': 'Unknown action'}), 400
        if not r.ok: errors += 1
    return jsonify({'processed': len(ids), 'errors': errors})

def init_settings():
    try:
        r = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/settings')
        if r.ok:
            print('Settings collection ready')
        else:
            print('Creating settings collection...')
            r = aw('POST', f'/v1/databases/{DATABASE_ID}/collections', _json=True, json={
                'collectionId': 'settings', 'name': 'settings',
                'permissions': ['read("any")','create("any")','update("any")','delete("any")'],
                'documentSecurity': True
            })
            if not r.ok:
                print(f'Create failed: {r.text}')
            else:
                import time as _time
                _time.sleep(2)
                for attr in [
                    {'key':'key','type':'string','size':256,'required':True},
                    {'key':'value','type':'string','size':8192,'required':True},
                ]:
                    aw('POST', f'/v1/databases/{DATABASE_ID}/collections/settings/attributes/string', _json=True, json=attr)
                defaults = [
                    ('splash_title','مكتبة حكاية'),
                    ('splash_subtitle','اكتشف عالم القراءة'),
                    ('splash_badge','اكتشف عالم القراءة'),
                    ('app_name','مكتبة حكاية'),
                    ('app_tagline','كل ما تحتاجه في مكان واحد'),
                    ('splash_word1_color','#E0A800'),
                    ('splash_word2_color','#E0A800'),
                    ('splash_bg_color','#FFFFFF'),
                    ('splash_subtitle_color','#8a8a93'),
                    ('splash_badge_bg','#FFDF73,#FFD700,#E0A800,#B8860B'),
                    ('splash_badge_text_color','#FFFFFF'),
                    ('whatsapp_number','+9647712345678'),
                    ('instagram_url','hikaya_store'),
                    ('facebook_url','hikaya.store'),
                    ('telegram_url','hikaya_store'),
                    ('tiktok_url','@hikaya_store'),
                    ('contact_phone','+9647712345678'),
                    ('contact_email','info@hikaya.store'),
                    ('primary_color','#E0A800'),
                    ('secondary_color','#FFD700'),
                    ('about_us','مكتبة حكاية - وجهتك الأولى لكل ما تحتاجه من كتب وأدوات مدرسية وألعاب.'),
                ]
                for k,v in defaults:
                    aw('POST', f'/v1/databases/{DATABASE_ID}/collections/settings/documents', _json=True, json={
                        'documentId': 'unique()', 'data': {'key': k, 'value': v},
                        'permissions': ['read("any")','write("any")']
                    })
                print('Settings collection initialized')
    except Exception as e:
        print(f'Init settings error: {e}')

def ensure_order_user_id():
    """Add userId attribute to orders collection if it doesn't exist."""
    try:
        r = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/orders/attributes/string/userId')
        if r.ok:
            print('Orders userId attribute ready')
            return
    except:
        pass
    try:
        r = aw('POST', f'/v1/databases/{DATABASE_ID}/collections/orders/attributes/string', _json=True, json={
            'key': 'userId', 'type': 'string', 'size': 64, 'required': False, 'default': ''
        })
        if r.ok:
            print('Created userId attribute on orders collection')
        else:
            print(f'Create userId attribute failed: {r.text}')
    except Exception as e:
        print(f'Ensure userId attribute error: {e}')

def ensure_order_attrs():
    """Ensure all custom attributes exist on orders collection."""
    specs = [
        {'key':'id', 'type':'string', 'size':16, 'required':False, 'default':''},
        {'key':'lat', 'type':'float', 'required':False, 'default':0, 'min':-90, 'max':90},
        {'key':'lng', 'type':'float', 'required':False, 'default':0, 'min':-180, 'max':180},
    ]
    for attr in specs:
        try:
            r = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/orders/attributes/{attr["key"]}')
            if r.ok: continue
        except:
            pass
        try:
            t = attr.pop('type')
            aw('POST', f'/v1/databases/{DATABASE_ID}/collections/orders/attributes/{t}', _json=True, json=attr)
            attr['type'] = t  # restore for potential retry
        except Exception as e:
            print(f'Ensure {attr["key"]} error: {e}')

def ensure_missing_settings():
    """Add any missing splash_* settings that weren't in the initial defaults."""
    required = [
        ('splash_badge', 'اكتشف عالم القراءة'),
        ('splash_word1_color', '#E0A800'),
        ('splash_word2_color', '#E0A800'),
        ('splash_bg_color', '#FFFFFF'),
        ('splash_subtitle_color', '#8a8a93'),
        ('splash_badge_bg', '#FFDF73,#FFD700,#E0A800,#B8860B'),
        ('splash_badge_text_color', '#FFFFFF'),
        ('splash_anim_duration', '700'),
        ('splash_anim_delay', '150'),
        ('splash_font_size', '72'),
        ('splash_subtitle_size', '14'),
        ('splash_badge_size', '10'),
    ]
    try:
        r = aw('GET', f'/v1/databases/{DATABASE_ID}/collections/settings/documents')
        existing = {d.get('key') for d in (r.json().get('documents') or [])}
    except:
        existing = set()
    for key, default in required:
        if key in existing:
            continue
        try:
            aw('POST', f'/v1/databases/{DATABASE_ID}/collections/settings/documents', _json=True, json={
                'documentId': 'unique()', 'data': {'key': key, 'value': default},
                'permissions': ['read("any")', 'write("any")']
            })
            print(f'Created missing setting: {key}')
        except Exception as e:
            print(f'Create {key} error: {e}')

with app.app_context():
    init_settings()
    ensure_order_user_id()
    ensure_order_attrs()
    ensure_missing_settings()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
