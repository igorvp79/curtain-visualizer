import os,re,uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from apps.company.models import Company
from apps.employees.models import Employee
from apps.directories.models import Client,Supplier,CatalogFolder,CatalogProduct,MeasureUnit,ServiceCategory,Service,ProductTypeCategory,ProductType,Room
from apps.directories.product_types_backend import validate_configuration
from apps.orders.models import Order,OrderEvent,OrderInstanceExecutor
from apps.orders.order_creation import create_numbered_order
from apps.orders.instances_backend import InstanceInput,mutate

class Command(BaseCommand):
    help='Initialize synthetic demo data only in the isolated demonstration database.'
    def handle(self,*args,**options):
        if not getattr(settings,'CRM_DEMO_MODE',False) or settings.SETTINGS_MODULE!='config.demo_settings':raise CommandError('This command runs only with config.demo_settings')
        pin=os.environ.get('CRM_DEMO_PIN','')
        if not re.fullmatch(r'[0-9]{4}',pin):raise CommandError('Set CRM_DEMO_PIN to exactly four digits in Render Environment')
        U=get_user_model()
        existing=set(U.objects.values_list('username',flat=True))
        if existing and not {'demo_owner','demo_designer','demo_cashier'}<=existing:raise CommandError('Refusing to seed an unfamiliar database')
        from apps.company.demo_references import prepare,mark,create_orders
        reference_revision=prepare()
        with transaction.atomic():
            users={};employees={}
            for username,name,roles,suffix in [('demo_owner','Демо — Собственник',['owner','manager'],'1'),('demo_designer','Демо — Дизайнер',['manager'],'9'),('demo_cashier','Демо — Касса',['cashier'],''),('demo_designer2','Демо — Второй дизайнер',['manager'],'8')]:
                owner=username=='demo_owner'
                user,_=U.objects.get_or_create(username=username,defaults={'is_superuser':owner,'is_staff':owner})
                user.set_password(pin);user.save(update_fields=['password']);users[username]=user
                employee,_=Employee.objects.get_or_create(user=user,defaults={'full_name':name,'roles':roles,'order_suffix':suffix});employees[username]=employee
            # Existing demo work stays intact across a process restart; fresh containers get examples again.
            if Order.objects.exists():
                self.stdout.write('Demo accounts ready; existing demonstration data preserved.');return
            if reference_revision:
                Employee.objects.get_or_create(full_name='Демо — Мастер пошива',kind='contractor',defaults={'roles':['master']})
                Employee.objects.get_or_create(full_name='Демо — Монтажник',kind='contractor',defaults={'roles':['installer']})
                create_orders(users,employees)
                mark(reference_revision)
                self.stdout.write('Reference snapshot imported; only synthetic demo accounts and clients created.')
                return
            Company.objects.update_or_create(pk=1,defaults={'name':'Демонстрационный салон','designer_own_orders_only':True,'vat_type':'included','vat_percent':5})
            master,_=Employee.objects.get_or_create(full_name='Демо — Мастер пошива',kind='contractor',defaults={'roles':['master']})
            Employee.objects.get_or_create(full_name='Демо — Монтажник',kind='contractor',defaults={'roles':['installer']})
            meter=MeasureUnit.objects.filter(full_name='Метр').first()
            if not meter:meter=MeasureUnit.objects.create(full_name='Метр',short_name='м')
            folder,_=CatalogFolder.objects.get_or_create(name='Демо — Ткани')
            CatalogFolder.objects.get_or_create(name='Демо — Карнизы')
            products=[]
            for name,price,cost,stock in [('Тюль однотонная',800,300,80),('Портьерная ткань',1800,750,50),('Лента шторная',90,30,200)]:
                products.append(CatalogProduct.objects.create(folder=folder,name=name,proposal_name=name,unit='Метр',retail_price=price,purchase_price=cost,stock=stock))
            category,_=ServiceCategory.objects.get_or_create(name='Пошив')
            services=[]
            for name,price,cost in [('Московский шов',100,50),('Пришивание тесьмы',100,45),('Шов с подгибкой',60,30)]:
                service,_=Service.objects.get_or_create(name=name,defaults={'category':category,'unit':meter,'service_price':price,'work_cost':cost});services.append(service)
            type_category,_=ProductTypeCategory.objects.get_or_create(name='Шторы')
            config=validate_configuration({'fields':[{'name':'width','label':'Ширина','kind':'decimal','default':'3','width':50},{'name':'height','label':'Высота','kind':'decimal','default':'2.7','width':50}],'goods':[{'item':products[0].pk,'formula':'result = param.width;'}],'services':[{'item':s.pk,'formula':'result = param.width'+(' * 4;' if i==0 else ';')} for i,s in enumerate(services)],'factors':[{'name':'Деликатная ткань','percent':'20','default':False,'goods':False,'services':True,'categories':[category.pk]}]})
            template,_=ProductType.objects.get_or_create(name='Тюль',category=type_category,defaults={'configuration':config})
            room=Room.objects.filter(name='Гостиная').first()
            if not room:room=Room.objects.create(name='Гостиная')
            Supplier.objects.get_or_create(name='Демо — Поставщик тканей',defaults={'email':'supplier@example.com','note':'Вымышленные данные для обсуждения'})
            today=timezone.localdate()
            for i,(surname,first) in enumerate([('Демо-Клиент','Анна'),('Демо-Клиент','Ирина'),('Демо-Клиент','Павел')]):
                designer=employees['demo_designer' if i!=1 else 'demo_designer2'];user=designer.user
                client=Client.objects.create(surname=surname,first_name=first,phone=f'7000000010{i}',address=f'Демонстрационная улица, дом {i+1}',responsible=designer,created_by=user,note='Вымышленный клиент')
                order,_=create_numbered_order(user=user,employee=designer,data={'request_id':uuid.uuid4(),'client':client,'order_date':today,'due_date':today+timedelta(days=7+i),'address':client.address,'partner':None,'partner_name':'','note':'Демо: можно менять для обсуждения. Данные могут сбрасываться.'})
                form=InstanceInput(data={'request_id':str(uuid.uuid4()),'name':'Тюль в гостиную','quantity':1,'room':room.pk,'product_type':template.pk,'values':{'width':str(3+i),'height':'2.7'}},order=order);form.is_valid(raise_exception=True)
                instance,_=mutate(order,user,form.validated_data)
                if i==1:order.status=Order.Status.REGISTRATION;order.save(update_fields=['status'])
                if i==2:
                    order.status=Order.Status.PRODUCTION;order.save(update_fields=['status'])
                    OrderInstanceExecutor.objects.create(instance=instance,category_id_snapshot=category.pk,employee=master,due_date=order.due_date,updated_by=users['demo_owner'])
        self.stdout.write('Synthetic demonstration data initialized. No working CRM data was imported.')
