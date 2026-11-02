"""Catalogue goods in order instances, with expiring CRM reservations."""
import hashlib
import json
import time
from decimal import Decimal
from django.db import transaction,IntegrityError,OperationalError
from django.db.models import Sum,F,DecimalField,ExpressionWrapper
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError,PermissionDenied,APIException
from apps.company.models import Company
from apps.directories.models import CatalogProduct,CatalogFolder
from apps.directories.type_calculation import quantity,money,CalculationError,number
from .models import Order,OrderInstance,OrderGood,OrderEvent


def reservations():
    return OrderGood.objects.filter(is_active=True,reserve=True,reserve_until__gte=timezone.localdate(),instance__is_active=True).exclude(instance__order__status__in=['completed','cancelled'])


def reserved_totals(ids=None,exclude=None):
    rows=reservations()
    if ids is not None:rows=rows.filter(product_id__in=ids)
    if exclude is not None:rows=rows.exclude(pk=exclude)
    expression=ExpressionWrapper(F('quantity')*F('instance__quantity'),output_field=DecimalField(max_digits=25,decimal_places=4))
    return {row['product_id']:row['total'] for row in rows.values('product_id').annotate(total=Sum(expression))}


def available(product,totals):
    return max(Decimal(0),product.stock-product.reserved-totals.get(product.pk,Decimal(0)))


def ensure_capacity(products):
    totals=reserved_totals([p.pk for p in products])
    for product in products:
        if product.stock-product.reserved-totals.get(product.pk,Decimal(0))<0:
            raise ValidationError({'quantity':f'Недостаточно свободного товара «{product.name}». Обновите наличие, уменьшите количество или выключите резерв.'})


def product_options(user,instance,line=None):
    products=CatalogProduct.objects.filter(is_active=True)
    if line:products=(products|CatalogProduct.objects.filter(pk=line.product_id)).distinct()
    products=list(products.select_related('folder'))
    totals=reserved_totals(exclude=line.pk if line else None)
    actual_totals=reserved_totals() if line else totals
    return {'today':str(timezone.localdate()),'can_view_cost':user.is_superuser,'folders':list(CatalogFolder.objects.values('id','name','parent')),'products':[{'id':p.pk,'name':p.name,'proposal_name':p.proposal_name,'folder':p.folder_id,'category_name':p.folder.name,'source_code':p.source_code,'article':p.article,'unit':p.unit,'retail_price':str(p.retail_price),'stock':str(p.stock),'available':str(available(p,totals)),'free':str(available(p,actual_totals)),**({'purchase_price':str(p.purchase_price)} if user.is_superuser else {})} for p in products]}


class GoodInput(serializers.Serializer):
    request_id=serializers.UUIDField(required=False)
    product=serializers.PrimaryKeyRelatedField(queryset=CatalogProduct.objects.filter(is_active=True))
    quantity=serializers.DecimalField(max_digits=18,decimal_places=8,min_value=Decimal('0.00000001'),max_value=Decimal('1000000000'))
    sale_price=serializers.DecimalField(max_digits=16,decimal_places=2,min_value=Decimal(0),max_value=Decimal('1000000000'),required=False)
    discount=serializers.DecimalField(max_digits=5,decimal_places=2,min_value=Decimal(0),max_value=Decimal(100),default=Decimal(0))
    reserve=serializers.BooleanField(default=False)
    reserve_until=serializers.DateField(required=False,allow_null=True,default=None)
    note=serializers.CharField(allow_blank=True,default='')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance:self.fields['product'].queryset=(self.fields['product'].queryset|CatalogProduct.objects.filter(pk=self.instance.product_id)).distinct()
    def to_internal_value(self,data):
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Это поле не задаётся при сохранении товара.' for key in extra})
        if self.instance and 'request_id' in data:raise ValidationError({'request_id':'Идентификатор создания не изменяется.'})
        return super().to_internal_value(data)
    def validate(self,data):
        if not self.instance and not data.get('request_id'):raise ValidationError({'request_id':'Обновите форму добавления товара.'})
        if data['reserve']:
            if not data['reserve_until']:raise ValidationError({'reserve_until':'Укажите, до какой даты действует резерв.'})
            if data['reserve_until']<timezone.localdate():raise ValidationError({'reserve_until':'Дата окончания резерва не может быть в прошлом.'})
        else:data['reserve_until']=None
        return data


def represent(row,user,totals=None):
    from .layered_adjustments import line_amounts
    values=line_amounts(row,'goods')
    amount=values['amount']
    total_qty=row.quantity*row.instance.quantity
    data={'id':row.pk,'product':row.product_id,'name':row.name,'proposal_name':row.proposal_name,'article':row.article,'folder':row.product.folder_id,'category_name':row.category_name,'unit':row.unit,'quantity':str(row.quantity),'total_quantity':str(total_qty),'sale_price':str(row.sale_price),'discount':values['discount'],'markup':values['markup'],'inherits_adjustment':values['inherit'],'amount':str(amount),'reserve':row.reserve,'reserve_until':str(row.reserve_until) if row.reserve_until else None,'reservation_active':bool(row.reserve and row.reserve_until and row.reserve_until>=timezone.localdate() and row.instance.is_active and row.instance.order.status not in ['completed','cancelled']),'note':row.note}
    if user.is_superuser:data['purchase_price']=str(row.purchase_price)
    if totals is not None:
        data['stock']=str(row.product.stock)
        data['available']=str(available(row.product,totals))
    return data


def list_goods(instance,user):
    rows=list(instance.goods.filter(is_active=True).select_related('product','instance__order'))
    totals=reserved_totals([row.product_id for row in rows])
    data=[represent(row,user,totals) for row in rows]
    return {'rows':data,'goods_total':str(sum((Decimal(row['amount']) for row in data),Decimal(0)))}


def mutate(order,instance,user,data,line=None,remove=False):
    from .views import can_edit_order
    payload=dict(data);token=payload.pop('request_id',None)
    canonical={k:v.pk if hasattr(v,'pk') else str(v) for k,v in payload.items()}
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    def repeated():
        found=OrderGood.objects.filter(creation_token=token).select_related('product','instance__order').first() if token else None
        if found:
            if not found.is_active or found.instance_id!=instance.pk or found.created_by_id!=user.pk or found.creation_fingerprint!=fingerprint:
                raise ValidationError({'request_id':'Этот запрос уже использован. Откройте форму заново.'})
            return found
    for attempt in range(8):
        try:
            with transaction.atomic():
                current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
                if not can_edit_order(user,current):raise PermissionDenied('Недостаточно прав для изменения товаров заказа.')
                instance=get_object_or_404(OrderInstance,pk=instance.pk,order=current,is_active=True)
                if not line and not remove:
                    previous=repeated()
                    if previous:return previous,False
                ids={line.product_id} if line else set()
                if not remove:ids.add(payload['product'].pk)
                products={p.pk:p for p in CatalogProduct.objects.select_for_update(of=('self',)).select_related('folder').filter(pk__in=ids).order_by('pk')}
                row=get_object_or_404(OrderGood.objects.select_for_update(),pk=line.pk,instance=instance,is_active=True) if line else None
                if remove:
                    row.is_active=False;row.save();action='good_removed'
                else:
                    settings,_=Company.objects.get_or_create(pk=1)
                    product=products[payload['product'].pk]
                    same=row and row.product_id==product.pk
                    if not same and not product.is_active:raise ValidationError({'product':'Этот товар больше недоступен для добавления.'})
                    unit=row.unit if same else product.unit
                    try:qty=quantity(payload['quantity'],unit,settings.quantity_places,settings.piece_rounding)
                    except CalculationError as e:raise ValidationError({'quantity':str(e)})
                    if qty<=0:raise ValidationError({'quantity':'После округления количество должно быть больше нуля.'})
                    values={**payload,'product':product,'quantity':qty,'sale_price':payload.get('sale_price',row.sale_price if same else product.retail_price)}
                    if not same:values.update(name=product.name,proposal_name=product.proposal_name,article=product.article,category_name=product.folder.name,unit=unit,purchase_price=product.purchase_price,money_places=settings.money_places)
                    places=row.money_places if same else settings.money_places
                    try:number(qty*values['sale_price']*instance.quantity)
                    except CalculationError:raise ValidationError({'quantity':'Стоимость строки выходит за допустимые пределы.'})
                    if row:
                        from .layered_adjustments import sync_line_discount
                        sync_line_discount(instance,row,'goods',values)
                        for key,value in values.items():setattr(row,key,value)
                        row.save();action='good_updated'
                    else:
                        row=OrderGood.objects.create(instance=instance,created_by=user,creation_token=token,creation_fingerprint=fingerprint,**values);action='good_created'
                    if row.reserve:ensure_capacity([product])
                from .composition_backend import update_order
                update_order(current)
                OrderEvent.objects.create(order=current,actor=user,action=action,details={'instance_id':instance.pk,'good_id':row.pk})
                return row,True
        except IntegrityError:
            previous=repeated()
            if previous:return previous,False
            raise ValidationError('Конфликт сохранения товара. Повторите попытку.')
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ['locked','busy']):raise
            if attempt==7:
                failure=APIException('База занята. Повторите сохранение через несколько секунд.');failure.status_code=503;raise failure
            time.sleep(.05*(attempt+1))
