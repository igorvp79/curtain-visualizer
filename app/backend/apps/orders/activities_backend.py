"""Local scheduled calls, meetings and visits. No external calendar side effects."""
import hashlib,json
from django.db import transaction,IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied,ValidationError,APIException
from .models import Order,OrderActivity,OrderEvent

FIELDS=['kind','title','date','time','duration','location','note']
class ActivityInput(serializers.Serializer):
    request_id=serializers.UUIDField(required=False)
    version=serializers.IntegerField(min_value=1,required=False)
    kind=serializers.ChoiceField(choices=['call','meeting','visit'])
    title=serializers.CharField(max_length=250)
    date=serializers.DateField()
    time=serializers.TimeField()
    duration=serializers.IntegerField(min_value=1,max_value=1440)
    location=serializers.CharField(max_length=500,allow_blank=True,default='')
    note=serializers.CharField(max_length=10000,allow_blank=True,default='')
    def to_internal_value(self,data):
        if set(data)-set(self.fields):raise serializers.ValidationError({'non_field_errors':['Недопустимые поля события.']})
        return super().to_internal_value(data)
    def validate(self,data):
        if data['kind'] in ['meeting','visit'] and not data['location']:raise serializers.ValidationError({'location':'Укажите место встречи.' if data['kind']=='meeting' else 'Укажите адрес выезда.'})
        if data['kind']=='call':data['location']=''
        if data['time'].tzinfo is not None:raise serializers.ValidationError({'time':'Укажите местное время Москвы без часового пояса.'})
        return data

class DeleteInput(serializers.Serializer):
    version=serializers.IntegerField(min_value=1)
    def to_internal_value(self,data):
        if set(data)-set(self.fields):raise serializers.ValidationError({'non_field_errors':['Недопустимые поля удаления.']})
        return super().to_internal_value(data)

def represent(row):
    return {'id':row.pk,**{key:getattr(row,key) for key in FIELDS},'kind_label':row.get_kind_display(),'version':row.version}

def mutate(order,user,data,activity_id=None,remove=False):
    from .views import can_edit_order
    values={key:data[key] for key in FIELDS if key in data}
    fingerprint=hashlib.sha256(json.dumps(values,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    try:
        with transaction.atomic():
            parent=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
            if not can_edit_order(user,parent):raise PermissionDenied('Изменять события может собственник или ответственный дизайнер открытого заказа.')
            created=False
            if activity_id is None:
                token=data.get('request_id')
                if not token:raise ValidationError({'request_id':'Обновите форму события.'})
                if 'version' in data:raise ValidationError({'version':'Версия не задаётся при создании.'})
                previous=OrderActivity.objects.filter(creation_token=token).first()
                if previous:
                    if previous.order_id!=parent.pk or previous.created_by_id!=user.pk or not previous.is_active or previous.fingerprint!=fingerprint:raise ValidationError({'request_id':'Этот запрос уже использован. Откройте форму заново.'})
                    return previous,False
                row=OrderActivity.objects.create(order=parent,created_by=user,creation_token=token,fingerprint=fingerprint,**values);created=True;action='activity_created'
            else:
                row=get_object_or_404(OrderActivity.objects.select_for_update(),pk=activity_id,order=parent,is_active=True)
                if 'request_id' in data:raise ValidationError({'request_id':'Нельзя изменить идентификатор создания.'})
                if data.get('version')!=row.version:
                    error=APIException('Событие уже изменено. Обновите список и откройте его заново.');error.status_code=409;raise error
                if remove:row.is_active=False;action='activity_removed'
                else:
                    if all(getattr(row,key)==value for key,value in values.items()):return row,False
                    for key,value in values.items():setattr(row,key,value)
                    action='activity_updated'
                row.version+=1;row.save()
            OrderEvent.objects.create(order=parent,actor=user,action=action,details={'activity_id':row.pk,'kind':row.kind})
        return row,created
    except IntegrityError:raise ValidationError({'request_id':'Этот запрос уже использован. Откройте форму заново.'})
