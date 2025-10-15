# PythonAnywhere Deployment Guide

## Prerequisites
1. **Account** Create or log in to your PythonAnywhere account (`username.pythonanywhere.com`).
2. **Python version** Decide which Python runtime you will use (e.g. Python 3.11). Make sure it matches your local version.
3. **Source repo** Ensure the `QA_tool` repository is pushed to GitHub and accessible from PythonAnywhere.

## 1. Create a virtual environment
```bash
mkvirtualenv --python=/usr/bin/python3.11 qa_tool_env
workon qa_tool_env
pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Clone the project on PythonAnywhere
```bash
cd ~
git clone https://github.com/Joelmaloba2541/QA_tool.git
cd QA_tool
```
If you already have the repo cloned, pull the latest changes instead.

## 3. Configure the Django app
1. Edit `qa_tool/settings.py` if you need to adjust `ALLOWED_HOSTS` (PythonAnywhere automatically serves from `<username>.pythonanywhere.com`, which is already covered by the wildcard entry).
2. Generate secret values as environment variables if you plan to run in production mode (optional but recommended). A typical pattern is to create a `.env` file and load it in `settings.py` using `python-dotenv`.

## 4. Run database migrations
```bash
python manage.py migrate
```
Create a superuser if desired:
```bash
python manage.py createsuperuser
```

## 5. Collect static files
```bash
python manage.py collectstatic --noinput
```
This will populate the `staticfiles/` directory, which PythonAnywhere can serve as a static directory.

## 6. Configure the PythonAnywhere web app
1. On the PythonAnywhere dashboard, go to **Web** ▸ **Add a new web app**.
2. Choose **Manual configuration** ➜ select the same Python version as your virtualenv.
3. In the **Virtualenv** field, enter `/home/<username>/.virtualenvs/qa_tool_env`.
4. In the **Code** section, set the source directory to `/home/<username>/QA_tool`.
5. Update the **WSGI configuration file** (typically `/var/www/<username>_pythonanywhere_com_wsgi.py`) so it points to `qa_tool.wsgi`. Replace the default contents with:
```python
import os
import sys

path = "/home/<username>/QA_tool"
if path not in sys.path:
    sys.path.append(path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qa_tool.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```
6. Configure static files:
   - **Static URL**: `/static/`
   - **Directory**: `/home/<username>/QA_tool/staticfiles`

## 7. Reload the web app
Click **Reload** on the Web dashboard. Visit `https://<username>.pythonanywhere.com/` to confirm the dashboard loads.

## 8. Scheduled tasks (optional)
If you ever add background audit jobs, configure PythonAnywhere scheduled tasks or consoles to run periodic management commands.

## 9. Updating the site
Whenever you push new changes to GitHub:
```bash
cd ~/QA_tool
git pull
workon qa_tool_env
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```
Finish by reloading the web app from the dashboard.
