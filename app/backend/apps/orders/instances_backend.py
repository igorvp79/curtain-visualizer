"""Instance headers, parameter snapshots and template composition."""
import copy
import hashlib
import json
import time
from decimal import Decimal
from django.db import transaction,IntegrityError,OperationalError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError,PermissionDenied,APIException
from .models import Order,OrderInstance,OrderEvent
from apps.directories.models import Room,ProductType,ProductTypeCategory
from apps.directories.type_calculation import number,CalculationError
from .composition_backend import factors


class InstanceInput(serializers.Serializer):
    request_id=serializers.UUIDField(required=False)
    name=serializers.CharField(max_length=250)
    quantity=serializers.IntegerField(min_value=1,max_value=100000,default=1)
    room=serializers.PrimaryKeyRelatedField(queryset=Room.objects.filter(is_active=True),allow_null=True,default=None)
    due_date=serializers.DateField(required=False)
    complexity=serializers.DecimalField(max_digits=8,decimal_places=2,min_value=Decimal('0.01'),max_value=Decimal('1000'),default=Decimal(1))
    product_type=serializers.PrimaryKeyRelatedField(queryset=ProductType.objects.filter(is_active=True),allow_null=True,default=None)
    values=serializers.JSONField(default=dict)
    enabled_factors=serializers.ListField(child=serializers.CharField(max_length=20),required=False)
    recalculate=serializers.BooleanField(default=False)
    note=serializers.CharField(allow_blank=True,default='')
    def __init__(self,*args,order,**kwargs):
        self.order=order
        super().__init__(*args,**kwargs)
        if self.instance:
            self.fields['request_id'].read_only=True
            self.fields['room'].queryset=Room.objects.filter(is_active=True)|Room.objects.filter(pk=self.instance.room_id)
            self.fields['product_type'].queryset=ProductType.objects.filter(is_active=True)|ProductType.objects.filter(pk=self.instance.product_type_id)
    def to_internal_value(self,data):
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Это поле не задаётся при сохранении изделия.' for key in extra})
        if self.instance and 'request_id' in data:raise ValidationError({'request_id':'Идентификатор создания не изменяется.'})
        return super().to_internal_value(data)
    def validate(self,data):
        if not self.instance and 'request_id' not in data:raise ValidationError({'request_id':'Обновите форму добавления изделия.'})
        data.setdefault('due_date',self.order.due_date)
        if data['due_date']<self.order.order_date:raise ValidationError({'due_date':'Дата сдачи не может быть раньше даты оформления заказа.'})
        template=data.get('product_type')
        same=self.instance and self.instance.product_type_id==getattr(template,'pk',None) and not data['recalculate']
        config=copy.deepcopy(self.instance.configuration if same else template.configuration if template else {})
        config['factors']=factors(config)
        if not same and template:
            from apps.directories.product_types_backend import validate_configuration
            try:config=validate_configuration(config)
            except (CalculationError,TypeError,ValueError) as error:raise ValidationError({'product_type':str(error)})
        enabled=data.get('enabled_factors',self.instance.enabled_factors if same else [f['id'] for f in config.get('factors',[]) if f.get('default')])
        if len(enabled)!=len(set(enabled)) or set(enabled)-{f['id'] for f in config.get('factors',[])}:raise ValidationError({'enabled_factors':'Неизвестная или повторяющаяся надбавка.'})
        data['enabled_factors']=enabled
        supplied=data['values']
        if not isinstance(supplied,dict):raise ValidationError({'values':'Параметры должны быть объектом.'})
        fields=config.get('fields',[])
        if not isinstance(fields,list) or len(fields)>100:raise ValidationError({'product_type':'Некорректные вводимые поля типа изделия.'})
        known={f['name'] for f in fields}
        if set(supplied)-known:raise ValidationError({'values':'Передан неизвестный параметр изделия.'})
        normalized={}
        try:
            for field in fields:
                value=number(supplied.get(field['name'],field.get('default',0)))
                if value<0:raise CalculationError(field['label']+': значение не может быть отрицательным.')
                if field['kind']=='integer' and value!=value.to_integral_value():raise CalculationError(field['label']+': нужно целое число.')
                if field['kind']=='list' and value not in [number(o['value']) for o in field['options']]:raise CalculationError(field['label']+': выберите значение из списка.')
                normalized[field['name']]=str(value)
        except CalculationError as error:raise ValidationError({'values':str(error)})
        data['values']=normalized
        data['configuration']=config
        data['type_name']=self.instance.type_name if same else template.name if template else ''
        room=data.get('room')
        data['room_name']=self.instance.room_name if self.instance and self.instance.room_id==getattr(room,'pk',None) else room.name if room else ''
        return data


def represent(row):
    return {'photo_url':f'/api/orders/{row.order_id}/instances/{row.pk}/photo/?v={row.photo.name.rsplit("/",1)[-1]}' if row.photo else None,'comment_count':row.comments.count(),'id':row.pk,'name':row.name,'quantity':row.quantity,'room':row.room_id,'room_name':row.room_name,'due_date':str(row.due_date),'complexity':str(row.complexity),'product_type':row.product_type_id,'type_name':row.type_name,'values':row.values,'fields':row.configuration.get('fields',[]),'factors':[{k:f.get(k) for k in ['id','name','percent','default','goods','services','categories']} for f in factors(row.configuration)],'enabled_factors':row.enabled_factors,'note':row.note,'created_at':row.created_at}


def options():
    return {'rooms':list(Room.objects.filter(is_active=True).values('id','name')),'categories':list(ProductTypeCategory.objects.values('id','name','parent')),'types':[{'id':t.pk,'name':t.name,'category':t.category_id,'fields':t.configuration.get('fields',[]),'factors':factors(t.configuration)} for t in ProductType.objects.filter(is_active=True)]}


def mutate(order,user,data,instance=None,remove=False):
    from .views import can_edit_order
    payload=dict(data)
    token=payload.pop('request_id',None)
    recalculate=payload.pop('recalculate',False)
    canonical={k:(v.pk if hasattr(v,'pk') else str(v) if not isinstance(v,(dict,list)) else v) for k,v in payload.items()}
    fingerprint=hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    def repeated():
        found=OrderInstance.objects.filter(creation_token=token).first() if token else None
        if found:
            if not found.is_active or found.order_id!=order.pk or found.created_by_id!=user.pk or found.creation_fingerprint!=fingerprint:
                raise ValidationError({'request_id':'Этот запрос уже использован. Откройте форму заново.'})
            return found
    for attempt in range(8):
        try:
            with transaction.atomic():
                locked=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
                if not can_edit_order(user,locked):raise PermissionDenied('Изменять изделия может собственник или ответственный дизайнер открытого заказа.')
                increasing=False
                stock_products=[]
                if not instance and not remove:
                    previous=repeated()
                    if previous:return previous,False
                    row=OrderInstance.objects.create(order=locked,created_by=user,creation_token=token,creation_fingerprint=fingerprint,**payload)
                    action='instance_created'
                    generate=True
                else:
                    row=get_object_or_404(OrderInstance,pk=instance.pk,order=locked,is_active=True)
                    generate=not remove and (recalculate or row.product_type_id!=getattr(payload.get('product_type'),'pk',None))
                    increasing=not remove and payload.get('quantity',row.quantity)>row.quantity
                    stock_products=[]
                    if increasing or generate:
                        from apps.directories.models import CatalogProduct
                        ids=set(row.goods.values_list('product_id',flat=True))
                        ids.update(rule['item'] for rule in payload.get('configuration',{}).get('goods',[]))
                        stock_products=list(CatalogProduct.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
                    if remove:row.is_active=False;action='instance_removed'
                    else:
                        for key,value in payload.items():setattr(row,key,value)
                        action='instance_updated'
                    row.save()
                from .composition_backend import populate,update_order
                if generate and not remove:populate(row,user)
                if increasing:
                    from .goods_backend import ensure_capacity,reservations
                    held=set(reservations().filter(instance=row).values_list('product_id',flat=True))
                    ensure_capacity([product for product in stock_products if product.pk in held])
                update_order(locked)
                locked.items_count=locked.instances.filter(is_active=True).count()
                locked.save(update_fields=['items_count','updated_at'])
                OrderEvent.objects.create(order=locked,actor=user,action=action,details={'instance_id':row.pk})
                return row,True
        except IntegrityError:
            previous=repeated()
            if previous:return previous,False
            raise ValidationError('Не удалось сохранить изделие из-за конфликта данных. Повторите попытку.')
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ['locked','busy']):raise
            if attempt==7:
                failure=APIException('База занята. Повторите сохранение через несколько секунд.');failure.status_code=503;raise failure
            time.sleep(.05*(attempt+1))
