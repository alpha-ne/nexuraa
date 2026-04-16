# 🛡️ Nexura — Quick Start Guide

## 1. Install Dependencies
```bash
pip install -r requirements.txt
```

## 2. Configure Environment
```bash
# .env already exists with safe defaults — DEBUG=True and OTP_TEST_MODE=True
# No API keys needed for local development (all sandbox/mock mode)
# Leave DB_NAME empty to use SQLite (default)
```

## 3. Run Migrations & Load Fixtures
```bash
python manage.py migrate
python manage.py makemigrations core  # if SupportTicket migration needed
python manage.py migrate
python manage.py loaddata fixtures/zones.json fixtures/plans.json
```

## 4. Create Static Files (copy main.js)
```bash
copy static\js\nexura.js static\js\main.js   # Windows
# cp static/js/nexura.js static/js/main.js   # Linux/Mac
```

## 5. Create an Admin User
```bash
python manage.py create_nexura_admin
# Enter any 10-digit mobile number (e.g. 9000000001)
```

## 6. Start the Server
```bash
python manage.py runserver
```

## 7. Access the Platform
| URL | Purpose |
|---|---|
| http://127.0.0.1:8000/ | Public site |
| http://127.0.0.1:8000/register/ | Worker registration |
| http://127.0.0.1:8000/login/ | Login (OTP = **123456**) |
| http://127.0.0.1:8000/admin-portal/ | Admin portal |
| http://127.0.0.1:8000/django-admin/ | Django admin |

## 8. Test the Full Pipeline

### From Admin Portal:
1. Login as admin → `/admin-portal/`
2. Use **"Fire Test Trigger"** → select zone + trigger type → click Fire
3. Go to **Claims list** → click Approve
4. Payout is queued (sandbox mode)

### From Worker Dashboard (DEBUG mode):
1. Login as worker → go to Dashboard
2. Scroll to **"🧪 Developer Mode"** panel → select trigger type → Simulate
3. Go to **My Claims** → see the pending claim

## Notes
- **OTP is always `123456`** when `OTP_TEST_MODE=True`
- **Celery not required** for development — claims created directly in simulate mode
- To run Celery: `celery -A nexura worker -l info` (requires Redis)
