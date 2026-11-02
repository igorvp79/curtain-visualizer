import unicodedata
from django.conf import settings
from django.db import models

def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()

class MeasureUnit(models.Model):
    full_name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20)
    name_key = models.CharField(max_length=300, unique=True, editable=False)
    short_key = models.CharField(max_length=100, editable=False)
    is_builtin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.full_name = " ".join(self.full_name.strip().split())
        self.short_name = " ".join(self.short_name.strip().split())
        self.name_key = normalize_name(self.full_name)
        self.short_key = normalize_name(self.short_name)
        super().save(*args,**kwargs)
    class Meta: ordering = ["id"]

class UnitEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    unit = models.ForeignKey(MeasureUnit,on_delete=models.PROTECT)
    action = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)


class Warehouse(models.Model):
    name=models.CharField(max_length=150)
    address=models.CharField(max_length=400)
    name_key=models.CharField(max_length=450,unique=True,editable=False)
    address_key=models.CharField(max_length=1200,editable=False)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.name=" ".join(self.name.strip().split())
        self.address=" ".join(self.address.strip().split())
        self.name_key=normalize_name(self.name)
        self.address_key=normalize_name(self.address)
        super().save(*args,**kwargs)
    class Meta:ordering=["id"]

class WarehouseEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    warehouse=models.ForeignKey(Warehouse,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class Supplier(models.Model):
    inn=models.CharField(max_length=12,blank=True)
    note=models.TextField(blank=True)
    name=models.CharField(max_length=250)
    phone=models.CharField(max_length=50,blank=True)
    phone_extension=models.CharField(max_length=10,blank=True)
    email=models.EmailField(blank=True)
    manager_name=models.CharField(max_length=250,blank=True)
    manager_phone=models.CharField(max_length=50,blank=True)
    manager_extension=models.CharField(max_length=10,blank=True)
    orders_email=models.EmailField(blank=True)
    max_discount=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    min_markup=models.DecimalField(max_digits=10,decimal_places=4,null=True,blank=True)
    ordering_notes=models.TextField(blank=True)
    name_key=models.CharField(max_length=750,editable=False)
    search_key=models.TextField(editable=False)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.name=" ".join(self.name.strip().split())
        self.name_key=normalize_name(self.name)
        self.search_key=normalize_name(" ".join([self.name,self.phone,self.email,self.manager_name,self.manager_phone,self.orders_email,self.inn,self.note]))
        super().save(*args,**kwargs)
    class Meta:ordering=["id"]

class SupplierEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class Client(models.Model):
    kind=models.CharField(max_length=10,choices=[('person','Физическое лицо'),('legal','Юридическое лицо')],default='person')
    organization_name=models.CharField(max_length=500,blank=True)
    inn=models.CharField(max_length=12,blank=True)
    kpp=models.CharField(max_length=9,blank=True)
    contact_name=models.CharField(max_length=250,blank=True)
    legal_address=models.CharField(max_length=1000,blank=True)
    account_number=models.CharField(max_length=20,blank=True)
    bank_name=models.CharField(max_length=250,blank=True)
    bank_bik=models.CharField(max_length=9,blank=True)
    correspondent_account=models.CharField(max_length=20,blank=True)
    surname=models.CharField(max_length=150,blank=True)
    first_name=models.CharField(max_length=150,blank=True)
    patronymic=models.CharField(max_length=150,blank=True)
    phone=models.CharField(max_length=40)
    phone_key=models.CharField(max_length=20,unique=True,editable=False)
    email=models.EmailField(blank=True)
    address=models.CharField(max_length=1000,blank=True)
    note=models.TextField(blank=True)
    source=models.CharField(max_length=150,default="Клиент салона")
    responsible=models.ForeignKey('employees.Employee',on_delete=models.PROTECT,related_name='clients')
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    is_private=models.BooleanField(default=False)
    is_active=models.BooleanField(default=True)
    name_key=models.CharField(max_length=1350,editable=False)
    search_key=models.TextField(editable=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.phone_key=normalize_phone(self.phone)
        self.name_key=normalize_name(self.organization_name if self.kind=='legal' else ' '.join([self.surname,self.first_name,self.patronymic]))
        self.search_key=normalize_name(' '.join([self.name_key,self.phone,self.phone_key,self.email,self.address,self.note,self.inn,self.kpp,self.contact_name,self.legal_address]))
        super().save(*args,**kwargs)
    class Meta:ordering=['name_key','id']

def normalize_phone(value):
    import re
    digits=re.sub(r'[^0-9]','',value)
    if len(digits)==11 and digits.startswith('8'):digits='7'+digits[1:]
    if len(digits)==10:digits='7'+digits
    return digits

class ClientEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    client=models.ForeignKey(Client,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class PriceType(models.Model):
    name=models.CharField(max_length=100)
    name_key=models.CharField(max_length=300,unique=True,editable=False)
    for_goods=models.BooleanField(default=True)
    for_services=models.BooleanField(default=True)
    is_base=models.BooleanField(default=False)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.name=' '.join(self.name.strip().split());self.name_key=normalize_name(self.name)
        super().save(*args,**kwargs)
    class Meta:
        ordering=['id']
        constraints=[models.UniqueConstraint(fields=['is_base'],condition=models.Q(is_base=True),name='single_base_price_type')]

class PriceTypeEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    price_type=models.ForeignKey(PriceType,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class CatalogFolder(models.Model):
    name=models.CharField(max_length=150)
    parent=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='children')
    class Meta:ordering=['name','id']

class CatalogProduct(models.Model):
    folder=models.ForeignKey(CatalogFolder,on_delete=models.PROTECT,related_name='products')
    source_code=models.CharField(max_length=30,blank=True)
    article=models.CharField(max_length=250,blank=True)
    name=models.CharField(max_length=250)
    proposal_name=models.CharField(max_length=250,blank=True)
    unit=models.CharField(max_length=50,blank=True)
    supplier=models.CharField(max_length=250,blank=True)
    retail_price=models.DecimalField(max_digits=16,decimal_places=2,default=0)
    purchase_price=models.DecimalField(max_digits=16,decimal_places=2,default=0)
    stock=models.DecimalField(max_digits=16,decimal_places=3,default=0)
    reserved=models.DecimalField(max_digits=16,decimal_places=3,default=0)
    is_active=models.BooleanField(default=True)
    class Meta:ordering=['name','id']


class ServiceCategory(models.Model):
    participates_in_production=models.BooleanField(default=True)
    name=models.CharField(max_length=150)
    parent=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='children')
    class Meta:ordering=['id']

class Service(models.Model):
    category=models.ForeignKey(ServiceCategory,on_delete=models.PROTECT,related_name='services')
    name=models.CharField(max_length=250)
    name_key=models.CharField(max_length=750,unique=True,editable=False)
    unit=models.ForeignKey(MeasureUnit,on_delete=models.PROTECT)
    work_cost=models.DecimalField(max_digits=16,decimal_places=2,default=0)
    service_price=models.DecimalField(max_digits=16,decimal_places=2,default=0)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        self.name=' '.join(self.name.strip().split());self.name_key=normalize_name(self.name)
        super().save(*args,**kwargs)
    class Meta:ordering=['id']

class ServiceEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    service=models.ForeignKey(Service,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class ProductTypeCategory(models.Model):
    name=models.CharField(max_length=150)
    parent=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='children')
    class Meta:ordering=['name','id']

class ProductType(models.Model):
    category=models.ForeignKey(ProductTypeCategory,on_delete=models.PROTECT,related_name='types')
    name=models.CharField(max_length=250)
    name_key=models.CharField(max_length=750,unique=True,editable=False)
    configuration=models.JSONField(default=dict)
    information=models.TextField(blank=True)
    proposal_caption=models.TextField(blank=True)
    is_active=models.BooleanField(default=True)
    def save(self,*args,**kwargs):
        self.name=' '.join(self.name.strip().split());self.name_key=normalize_name(self.name)
        super().save(*args,**kwargs)
    class Meta:ordering=['name','id']

class ProductTypeEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    product_type=models.ForeignKey(ProductType,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class ClientSource(models.Model):
    name=models.CharField(max_length=150)
    name_key=models.CharField(max_length=450,unique=True,editable=False)
    is_active=models.BooleanField(default=True)
    def save(self,*args,**kwargs):
        self.name=' '.join(self.name.strip().split())
        self.name_key=normalize_name(self.name)
        super().save(*args,**kwargs)
    class Meta:ordering=['id']

class ClientSourceEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    source=models.ForeignKey(ClientSource,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class Partner(models.Model):
    kind=models.CharField(max_length=10,choices=[('person','Физическое лицо'),('legal','Юридическое лицо')],default='person')
    organization_name=models.CharField(max_length=500,blank=True)
    inn=models.CharField(max_length=12,blank=True)
    kpp=models.CharField(max_length=9,blank=True)
    contact_name=models.CharField(max_length=250,blank=True)
    legal_address=models.CharField(max_length=1000,blank=True)
    account_number=models.CharField(max_length=20,blank=True)
    bank_name=models.CharField(max_length=250,blank=True)
    bank_bik=models.CharField(max_length=9,blank=True)
    correspondent_account=models.CharField(max_length=20,blank=True)
    surname=models.CharField(max_length=150,blank=True)
    first_name=models.CharField(max_length=150,blank=True)
    patronymic=models.CharField(max_length=150,blank=True)
    phone=models.CharField(max_length=40)
    phone_key=models.CharField(max_length=20,unique=True,editable=False)
    email=models.EmailField(blank=True)
    address=models.CharField(max_length=1000,blank=True)
    note=models.TextField(blank=True)
    source=models.CharField(max_length=150,default="Клиент салона")
    responsible=models.ForeignKey('employees.Employee',on_delete=models.PROTECT,related_name='partners')
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    is_private=models.BooleanField(default=False)
    is_active=models.BooleanField(default=True)
    name_key=models.CharField(max_length=1350,editable=False)
    search_key=models.TextField(editable=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def save(self,*args,**kwargs):
        self.phone_key=normalize_phone(self.phone)
        self.name_key=normalize_name(self.organization_name if self.kind=='legal' else ' '.join([self.surname,self.first_name,self.patronymic]))
        self.search_key=normalize_name(' '.join([self.name_key,self.phone,self.phone_key,self.email,self.address,self.note,self.inn,self.kpp,self.contact_name,self.legal_address]))
        super().save(*args,**kwargs)
    class Meta:ordering=['name_key','id']

class PartnerEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    partner=models.ForeignKey(Partner,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)


class Room(models.Model):
    name=models.CharField(max_length=150)
    name_key=models.CharField(max_length=450,unique=True,editable=False)
    is_active=models.BooleanField(default=True)
    def save(self,*args,**kwargs):
        self.name=' '.join(self.name.split());self.name_key=normalize_name(self.name)
        super().save(*args,**kwargs)
    class Meta:ordering=['id']

class RoomEvent(models.Model):
    room=models.ForeignKey(Room,on_delete=models.PROTECT)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action=models.CharField(max_length=20)
    created_at=models.DateTimeField(auto_now_add=True)
