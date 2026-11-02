"""Instance-wide price adjustments, separate from line prices and template factors."""
import time
from decimal import Decimal,DecimalException
from django.db import transaction,OperationalError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError,PermissionDenied,APIException
from apps.directories.type_calculation import money,number,CalculationError
from .models import Order,OrderInstance,OrderEvent

DEFAULTS={'scope':'all','discount_kind':'percent','discount_value':'0','markup_kind':'percent','markup_value':'0'}

class AdjustmentInput(serializers.Serializer):
    scope=serializers.ChoiceField(choices=['all','goods','services'])
    discount_kind=serializers.ChoiceField(choices=['percent','amount'])
    discount_value=serializers.DecimalField(max_digits=18,decimal_places=4,min_value=Decimal(0),max_value=Decimal('1000000000'))
    markup_kind=serializers.ChoiceField(choices=['percent','amount'])
    markup_value=serializers.DecimalField(max_digits=18,decimal_places=4,min_value=Decimal(0),max_value=Decimal('1000000000'))
    def to_internal_value(self,data):
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Это поле не задаётся в скидке и наценке.' for key in extra})
        return super().to_internal_value(data)
    def validate(self,data):
        if data['discount_kind']=='percent' and data['discount_value']>100:raise ValidationError({'discount_value':'Скидка не может превышать 100%.'})
        if data['markup_kind']=='percent' and data['markup_value']>1000:raise ValidationError({'markup_value':'Наценка не может превышать 1000%.'})
        return {key:str(value) for key,value in data.items()}


def calculate(instance,subtotal,goods,services,override=None):
    rule={**DEFAULTS,**(instance.price_adjustment if override is None else override)}
    base={'all':subtotal,'goods':goods,'services':services}[rule['scope']]
    requested_discount=money(base*Decimal(rule['discount_value'])/100 if rule['discount_kind']=='percent' else Decimal(rule['discount_value']),instance.money_places)
    requested_markup=money(base*Decimal(rule['markup_value'])/100 if rule['markup_kind']=='percent' else Decimal(rule['markup_value']),instance.money_places)
    discount=min(base,requested_discount)
    markup=requested_markup if base>0 else Decimal(0)
    total=money(subtotal+markup-discount,instance.money_places)
    number(total)
    return {**rule,'base':str(base),'discount_amount':str(discount),'markup_amount':str(markup),'discount_limited':discount<requested_discount,'markup_limited':markup<requested_markup,'total':str(total)}


def checked_summary(instance,user,rule):
    from .composition_backend import summary
    try:result=summary(instance,user,adjustment=rule)
    except (CalculationError,DecimalException) as error:raise ValidationError({'discount_value':str(error)})
    detail=result['adjustment']
    if rule.get('version')==2:
        from .layered_adjustments import validate_rows
        validate_rows(instance,rule)
        if detail['general']['correction_limited']:raise ValidationError({'general':'Корректировка в рублях превышает итог после процентов или в изделии нет стоимости.'})
        return result
    if detail['discount_limited']:raise ValidationError({'discount_value':'Скидка в рублях превышает стоимость выбранной области.'})
    if Decimal(detail['base'])<=0 and (Decimal(rule['discount_value'])>0 or Decimal(rule['markup_value'])>0):raise ValidationError({'scope':'В выбранной области нет стоимости для применения скидки или наценки.'})
    return result


def apply(order,instance,user,rule):
    from .views import can_edit_order
    from .composition_backend import update_order
    for attempt in range(8):
        try:
            with transaction.atomic():
                current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
                if not can_edit_order(user,current):raise PermissionDenied('Изменять скидку и наценку может собственник или ответственный дизайнер открытого заказа.')
                row=get_object_or_404(OrderInstance,pk=instance.pk,order=current,is_active=True)
                result=checked_summary(row,user,rule)
                if row.price_adjustment!=rule:
                    row.price_adjustment=rule;row.save(update_fields=['price_adjustment','updated_at'])
                    update_order(current)
                    OrderEvent.objects.create(order=current,actor=user,action='adjustment_updated',details={'instance_id':row.pk,'adjustment':rule})
                return result
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ['locked','busy']):raise
            if attempt==7:
                failure=APIException('База занята. Повторите сохранение через несколько секунд.');failure.status_code=503;raise failure
            time.sleep(.05*(attempt+1))
