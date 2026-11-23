# Diocesan Parish Quarterly Returns Portal

Web portal for the **Catholic Archdiocese of Ibadan** to collect, review, and track quarterly parish returns ("pink sheet"), Cathedraticum (25% levy on levyable income), waivers, payments, and priest transfers.

## Local setup

```powershell
python manage.py migrate
python manage.py load_pink_sheet
python manage.py import_priests "PRIERTS IN PARISHES PER DEANERY (26-08-26).docx"
python manage.py create_periods --year 2026
python manage.py createsuperuser
python manage.py runserver
```

- **Priest portal:** `http://127.0.0.1:8000/portal/`
- **Chancery portal:** `http://127.0.0.1:8000/chancery/`
- **Django Admin:** `http://127.0.0.1:8000/admin/`

## Daily email reminders

Schedule once per day (cron / Windows Task Scheduler / Railway cron):

```powershell
python manage.py send_reminders
```

Reminders are sent **14 days** and **3 days** before the due date, **on** the due date, and **every 7 days** while overdue. Chancery staff receive a weekly digest on Mondays.

## Production environment variables

Copy into `.env` (or hosting dashboard):

- `SECRET_KEY` — long random string
- `DEBUG=False`
- `DATABASE_URL` — PostgreSQL connection string (`postgres://...`)
- `ALLOWED_HOSTS` — comma-separated hostnames
- `CSRF_TRUSTED_ORIGINS` — e.g. `https://returns.example.org`
- `SITE_URL` — public base URL for email links
- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
