from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied,ValidationError
from apps.employees.models import Employee
from apps.employees.roles import ROLES,CONTRACTOR_ROLES
from .models import Order,OrderInstance,OrderInstanceExecutor,OrderEvent


def available(employee):
    return not employee.is_blocked and bool(set(employee.roles)&CONTRACTOR_ROLES) and (not employee.user_id or employee.user.is_active)


def groups(instance):
    result={}
    for service in instance.services.filter(is_active=True):
        if service.category_id_snapshot is None:continue
        group=result.setdefault(service.category_id_snapshot,{'category':service.category_id_snapshot,'category_name':service.category_name,'service_count':0})
        group['service_count']+=1
    return result


def summary(order,instance,user):
    from .views import can_edit_order
    assignments={row.category_id_snapshot:row for row in instance.executors.select_related('employee__user')}
    rows=[]
    for key,group in groups(instance).items():
        assigned=assignments.get(key);employee=assigned.employee if assigned else None
        rows.append({**group,'employee':employee.pk if employee else None,'employee_name':employee.full_name if employee else '', 'employee_available':available(employee) if employee else True,'version':assigned.updated_at if assigned else None,'technical_note':assigned.technical_note if assigned else '', 'started_at':assigned.started_at if assigned else None,'completed_at':assigned.completed_at if assigned else None,'due_date':str(assigned.due_date) if assigned and assigned.due_date else None})
    employees=[{'id':e.pk,'name':e.full_name,'roles':[ROLES[r] for r in e.roles if r in CONTRACTOR_ROLES],'kind':e.kind} for e in Employee.objects.select_related('user').all() if available(e)] if can_edit_order(user,order) else []
    return {'rows':rows,'employees':employees}


class ExecutorInput(serializers.Serializer):
    category=serializers.IntegerField(min_value=1)
    employee=serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(),allow_null=True)
    due_date=serializers.DateField(allow_null=True)
    version=serializers.DateTimeField(required=False,allow_null=True)
    technical_note=serializers.CharField(max_length=10000,allow_blank=True,required=False)
    def to_internal_value(self,data):
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Это поле нельзя изменить здесь.' for key in extra})
        return super().to_internal_value(data)


def assign(order,instance,user,data):
    from .views import can_edit_order
    with transaction.atomic():
        current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
        if not can_edit_order(user,current):raise PermissionDenied('Назначать исполнителей может собственник или ответственный дизайнер открытого заказа.')
        active=get_object_or_404(OrderInstance,order=current,pk=instance.pk,is_active=True)
        category=data['category'];employee=data['employee'];due=data['due_date']
        if category not in groups(active):raise ValidationError({'category':'В изделии нет услуг этой категории. Обновите список.'})
        previous=active.executors.filter(category_id_snapshot=category).first()
        if employee:
            employee=get_object_or_404(Employee.objects.select_related('user'),pk=employee.pk)
            if not available(employee) and (not previous or previous.employee_id!=employee.pk):raise ValidationError({'employee':'Сотрудник заблокирован или не имеет исполнительской роли. Выберите другого.'})
        else:due=None
        if due and due<current.order_date:raise ValidationError({'due_date':'Срок изготовления не может быть раньше даты оформления заказа.'})
        if 'version' in data and data['version']!=(previous.updated_at if previous else None):raise ValidationError('Назначение изменилось. Откройте задание заново.')
        note=data.get('technical_note',previous.technical_note if previous else '')
        if previous and previous.started_at and previous.employee_id!=(employee.pk if employee else None):raise ValidationError({'employee':'Работа уже принята мастером. Смена исполнителя на этом этапе недоступна.'})
        if previous and previous.technical_note==note and previous.employee_id==(employee.pk if employee else None) and previous.due_date==due:return
        row,created=OrderInstanceExecutor.objects.update_or_create(instance=active,category_id_snapshot=category,defaults={'employee':employee,'due_date':due,'technical_note':note,'updated_by':user})
        if created and employee is None and due is None:return
        OrderEvent.objects.create(order=current,actor=user,action='instance_executor_updated',details={'instance_id':active.pk,'category_id':category,'employee_id':employee.pk if employee else None})


def list_summaries(instances):
    """All categories, including installation/delivery, in two bounded queries."""
    from .models import OrderService
    ids=[row.pk for row in instances]
    result={pk:{} for pk in ids}
    for service in OrderService.objects.filter(instance_id__in=ids,is_active=True).order_by('id'):
        if service.category_id_snapshot is None:continue
        result[service.instance_id].setdefault(service.category_id_snapshot,{'category':service.category_name,'employee_name':''})
    for assignment in OrderInstanceExecutor.objects.filter(instance_id__in=ids).select_related('employee'):
        entry=result[assignment.instance_id].get(assignment.category_id_snapshot)
        if entry is not None and assignment.employee_id:entry['employee_name']=assignment.employee.full_name
    return {pk:list(categories.values()) for pk,categories in result.items()}
