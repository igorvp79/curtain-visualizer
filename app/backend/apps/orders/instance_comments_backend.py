"""Separate comment threads for order instances, with idempotent submission."""
import time
from django.db import transaction,IntegrityError,OperationalError
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError,PermissionDenied,APIException
from apps.employees.models import Employee
from .models import Order,OrderInstance,OrderComment,OrderEvent

class CommentInput(serializers.Serializer):
    request_id=serializers.UUIDField()
    text=serializers.CharField(max_length=10000,allow_blank=False,trim_whitespace=True)
    def to_internal_value(self,data):
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Это поле не задаётся при отправке комментария.' for key in extra})
        return super().to_internal_value(data)


def list_comments(instance):
    rows=list(instance.comments.select_related('actor').all())
    names=dict(Employee.objects.filter(user_id__in=[row.actor_id for row in rows]).values_list('user_id','full_name'))
    return [{'id':row.pk,'text':row.text,'created_at':row.created_at,'actor_name':names.get(row.actor_id,row.actor.get_username())} for row in rows]


def create(order,instance,user,data):
    from .views import can_edit_order
    token=data['request_id'];text=data['text']
    def repeated():
        row=OrderComment.objects.filter(creation_token=token).first()
        if row:
            if row.order_id!=order.pk or row.instance_id!=instance.pk or row.actor_id!=user.pk or row.text!=text:raise ValidationError({'request_id':'Не удалось повторить отправку. Скопируйте текст и откройте вкладку заново.'})
            return row
    for attempt in range(8):
        try:
            with transaction.atomic():
                current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
                if not can_edit_order(user,current):raise PermissionDenied('Добавлять комментарии может собственник или ответственный дизайнер открытого заказа.')
                current_instance=get_object_or_404(OrderInstance,pk=instance.pk,order=current,is_active=True)
                previous=repeated()
                if previous:return False
                row=OrderComment.objects.create(order=current,instance=current_instance,actor=user,text=text,creation_token=token)
                OrderEvent.objects.create(order=current,actor=user,action='instance_comment_added',details={'instance_id':instance.pk,'comment_id':row.pk})
                return True
        except IntegrityError:
            if repeated():return False
            raise ValidationError('Не удалось сохранить комментарий. Повторите отправку.')
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ['locked','busy']):raise
            if attempt==7:
                failure=APIException('База занята. Повторите отправку через несколько секунд.');failure.status_code=503;raise failure
            time.sleep(.05*(attempt+1))
