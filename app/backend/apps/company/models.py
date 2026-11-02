from uuid import uuid4
from django.conf import settings
from django.db import models

def image_path(instance, filename):
    return f"company/{instance.pk}/{uuid4().hex}.{filename.rsplit('.', 1)[-1].lower()}"

class Company(models.Model):
    profitability_threshold=models.PositiveSmallIntegerField(default=30)
    vat_type=models.CharField(max_length=10,default='none',choices=[('none','Без НДС'),('included','Включён в стоимость')])
    vat_percent=models.PositiveSmallIntegerField(default=5,choices=[(n,str(n)) for n in [5,7,20,22]])
    quantity_places=models.PositiveSmallIntegerField(default=2)
    money_places=models.PositiveSmallIntegerField(default=2)
    piece_rounding=models.CharField(max_length=10,default='up',choices=[('up','Вверх'),('nearest','Математически')])
    show_fully_paid_orders_in_payments = models.BooleanField(default=False)
    designer_own_orders_only = models.BooleanField(default=False)
    confirm_deletion = models.BooleanField(default=True)
    # This installation has one company profile, with any number of legal entities.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=199, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    currency = models.CharField(max_length=3, default="RUB", choices=[("RUB", "Российский рубль")])
    instagram = models.CharField(max_length=255, blank=True)
    vk = models.CharField(max_length=255, blank=True)
    telegram = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class Organization(models.Model):
    class Kind(models.TextChoices):
        PERSON = "person", "Физическое лицо"
        SELF_EMPLOYED = "self_employed", "Самозанятый"
        ENTREPRENEUR = "entrepreneur", "Индивидуальный предприниматель"
        LEGAL_ENTITY = "legal_entity", "Юридическое лицо"
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ENTREPRENEUR)
    full_name = models.CharField(max_length=199)
    short_name = models.CharField(max_length=199)
    legal_address = models.CharField(max_length=500)
    inn = models.CharField(max_length=12, blank=True)
    kpp = models.CharField(max_length=9, blank=True)
    ogrn = models.CharField(max_length=13, blank=True)
    ogrnip = models.CharField(max_length=15, blank=True)
    director = models.CharField(max_length=199, blank=True)
    accountant = models.CharField(max_length=199, blank=True)
    uses_vat = models.BooleanField(default=False)
    vat_mode = models.CharField(max_length=12, choices=[("included", "Включён в стоимость"), ("additional", "Начисляется дополнительно")], default="included")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=255, blank=True)
    bank_bik = models.CharField(max_length=9, blank=True)
    bank_account = models.CharField(max_length=20, blank=True)
    bank_correspondent_account = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to=image_path, blank=True)
    signature = models.ImageField(upload_to=image_path, blank=True)
    stamp = models.ImageField(upload_to=image_path, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["id"]

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=64)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
