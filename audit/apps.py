from django.apps import AppConfig


def _bootstrap_subscription_plans(sender, **kwargs):
    try:
        from .models import SubscriptionPlan

        SubscriptionPlan.bootstrap_defaults()
    except Exception:
        pass


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


def _ensure_default_admin_post_migrate(sender, **kwargs):
    _ensure_default_admin()


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(_bootstrap_subscription_plans, sender=self, weak=False)
        post_migrate.connect(_ensure_default_admin_post_migrate, sender=self, weak=False)
