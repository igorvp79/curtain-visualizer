from uuid import uuid4
from django.conf import settings
from django.db import models

def avatar_path(instance, filename):
    return f"employees/{instance.pk}/{uuid4().hex}.png"

class Employee(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="employee")
    kind = models.CharField(max_length=12, choices=[("staff", "Штатный"), ("contractor", "Подрядный")], default="staff")
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Moscow")
    roles = models.JSONField(default=list)
    order_suffix = models.CharField(max_length=20, blank=True)
    own_orders_only = models.BooleanField(default=False)
    own_clients_only = models.BooleanField(default=False)
    all_financial_operations = models.BooleanField(default=False)
    can_export_stock = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    avatar = models.ImageField(upload_to=avatar_path, blank=True)
    position = models.CharField(max_length=150, blank=True)
    about = models.TextField(blank=True)
    telegram = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["full_name", "id"]

class EmployeeEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
