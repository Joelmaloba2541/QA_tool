# Render Deployment Guide

## Prerequisites
1. **Render account** Sign up or log in at https://dashboard.render.com.
2. **PostgreSQL database** (recommended) Create a Render-managed PostgreSQL instance or supply an existing connection string.
3. **Repository** Ensure `https://github.com/Joelmaloba2541/QA_tool.git` is up-to-date with the latest code and contains `requirements.txt` plus this guide.

## 1. Configure environment variables
On Render, create a new Web Service and set the following environment variables under the **Environment** tab:

- `DJANGO_SECRET_KEY` A secure random string.
- `DJANGO_DEBUG` `False`
- `DATABASE_URL` (auto-populated if you link a Render PostgreSQL instance) or provide your own connection string.
- `WEB_CONCURRENCY` `2` (or another desired number of Gunicorn workers).

Optional variables:
- `ALLOWED_HOSTS` (Render handles this with `.onrender.com`, already in settings.)

## 2. Build & start commands
When creating the Web Service, use:

**Build Command**
```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
```

**Start Command**
```bash
gunicorn qa_tool.wsgi:application
```

## 3. Static files
Static assets are served via WhiteNoise. After `collectstatic`, Render will serve from `/static/` automatically.

## 4. Database migrations
Migrations run during the build step. If you need to trigger them manually later, open a Render shell and run:
```bash
python manage.py migrate
```

## 5. Managing superuser
To create an admin user on Render:
```bash
python manage.py createsuperuser
```
Run the command via a Render shell.

## 6. Redeploying
On every push to the `main` branch, Render can auto-deploy. The service will execute the build command, apply migrations, collect static files, and restart Gunicorn.

## 7. Custom domains (optional)
If you plan to use a custom domain, add it in the Render dashboard and update DNS records accordingly. Ensure the domain is added to `ALLOWED_HOSTS` or set `ALLOWED_HOSTS` via environment variables.

## 8. Troubleshooting
- **Collectstatic errors** Ensure `STATIC_ROOT` exists and that dependencies installed correctly.
- **Database connection issues** Verify the `DATABASE_URL` and SSL settings for your PostgreSQL instance.
