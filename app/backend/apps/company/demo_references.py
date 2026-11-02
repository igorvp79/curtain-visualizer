"""Import an explicitly exported reference snapshot only into the disposable demo database."""
import hashlib,json
from pathlib import Path
from django.conf import settings
from django.core import serializers
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from apps.company.models import Company

SNAPSHOT=Path(__file__).with_name('demo_reference.json')
ALLOWED={'directories.measureunit','directories.warehouse','directories.pricetype','directories.catalogfolder','directories.catalogproduct','directories.servicecategory','directories.service','directories.producttypecategory','directories.producttype','directories.clientsource','directories.room'}
SETTING_FIELDS={'profitability_threshold','show_fully_paid_orders_in_payments','quantity_places','money_places','piece_rounding','designer_own_orders_only','confirm_deletion','vat_type','vat_percent'}

def guard():
    if not getattr(settings,'CRM_DEMO_MODE',False) or settings.SETTINGS_MODULE!='config.demo_settings':raise CommandError('Reference import is only allowed in the isolated demo')
    expected=Path(settings.DEMO_ROOT).resolve()/'demo.sqlite3'
    if Path(settings.DATABASES['default']['NAME']).resolve()!=expected:raise CommandError('Demo database path mismatch')


def prepare():
    guard()
    if not SNAPSHOT.exists():return None
    content=SNAPSHOT.read_bytes();digest=hashlib.sha256(content).hexdigest();marker=Path(settings.DEMO_ROOT)/'reference-revision.txt'
    if marker.exists() and marker.read_text(encoding='utf-8')==digest:return digest
    data=json.loads(content)
    if data.get('version')!=1 or set(data)-{'version','objects','settings','counts'}:raise CommandError('Unsupported reference snapshot')
    if set(data['settings'])-SETTING_FIELDS or any(row['model'] not in ALLOWED for row in data['objects']):raise CommandError('Snapshot contains unsupported data')
    # A new reference revision replaces only the disposable demonstration database.
    call_command('flush',interactive=False,verbosity=0)
    with transaction.atomic():
        for item in serializers.deserialize('json',json.dumps(data['objects']),ignorenonexistent=False):item.save()
        Company.objects.update_or_create(pk=1,defaults={'name':'Демонстрационный салон',**data['settings']})
    return digest


def mark(digest):
    if digest:
        marker=Path(settings.DEMO_ROOT)/'reference-revision.txt'
        transaction.on_commit(lambda:marker.write_text(digest,encoding='utf-8'))


def create_orders(users,employees):
    import uuid
    from datetime import timedelta
    from django.utils import timezone
    from rest_framework.exceptions import ValidationError
    from apps.directories.models import Client,Room,ProductType
    from apps.orders.models import OrderNumberCounter
    from apps.orders.order_creation import create_numbered_order
    from apps.orders.instances_backend import InstanceInput,mutate
    OrderNumberCounter.objects.get_or_create(pk=1,defaults={'next_number':1})
    today=timezone.localdate();room=Room.objects.filter(is_active=True).first();templates=list(ProductType.objects.filter(is_active=True))
    for i,first in enumerate(['Анна','Ирина','Павел']):
        designer=employees['demo_designer' if i!=1 else 'demo_designer2'];user=designer.user
        client=Client.objects.create(surname='Демо-Клиент',first_name=first,phone=f'7000000010{i}',address=f'Демонстрационная улица, дом {i+1}',responsible=designer,created_by=user,note='Вымышленный клиент')
        order,_=create_numbered_order(user=user,employee=designer,data={'request_id':uuid.uuid4(),'client':client,'order_date':today,'due_date':today+timedelta(days=7+i),'address':client.address,'partner':None,'partner_name':'','note':'Демо с копией справочников. Примеры клиентов вымышленные.'})
        made=False
        for template in templates:
            try:
                with transaction.atomic():
                    form=InstanceInput(data={'request_id':str(uuid.uuid4()),'name':template.name,'quantity':1,'room':room.pk if room else None,'product_type':template.pk,'values':{}},order=order)
                    form.is_valid(raise_exception=True);mutate(order,user,form.validated_data);made=True
            except ValidationError:continue
            if made:break
        if not made:
            form=InstanceInput(data={'request_id':str(uuid.uuid4()),'name':'Демо-изделие','quantity':1,'room':room.pk if room else None,'product_type':None,'values':{}},order=order)
            form.is_valid(raise_exception=True);mutate(order,user,form.validated_data)
