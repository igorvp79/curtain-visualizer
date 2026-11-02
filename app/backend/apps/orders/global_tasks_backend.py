from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from apps.employees.models import Employee
from .models import OrderTask
from .tasks_backend import options,TaskInput,TaskActionInput,represent,mutate
class TaskUser(BasePermission):
    def has_permission(self,request,view):
        u=request.user
        return bool(u.is_authenticated and u.is_active and (u.is_superuser or Employee.objects.filter(user=u,is_blocked=False).exists()))
class Tasks(viewsets.ViewSet):
    permission_classes=[TaskUser]
    @action(detail=False,methods=['get'],url_path='options')
    def task_options(self,request):
        return Response({**options(None,request.user),'user_id':request.user.pk})
    def list(self,request):
        rows=OrderTask.objects.filter(is_active=True).select_related('order','created_by','created_by__employee').prefetch_related('assignees').order_by('due_date','id')
        return Response([represent(r,request.user) for r in rows])
    def create(self,request):
        form=TaskInput(data=request.data);form.is_valid(raise_exception=True)
        row,created=mutate(None,request.user,form.validated_data,global_mode=True)
        return Response(represent(row,request.user),status=201 if created else 200)
    def partial_update(self,request,pk=None):
        form=TaskInput(data=request.data);form.is_valid(raise_exception=True)
        row,_=mutate(None,request.user,form.validated_data,pk,global_mode=True)
        return Response(represent(row,request.user))
    def destroy(self,request,pk=None):
        form=TaskActionInput(data=request.data);form.is_valid(raise_exception=True)
        mutate(None,request.user,form.validated_data,pk,action='delete',global_mode=True)
        return Response(status=204)
    @action(detail=True,methods=['post'])
    def completion(self,request,pk=None):
        form=TaskActionInput(data=request.data);form.is_valid(raise_exception=True)
        row,_=mutate(None,request.user,form.validated_data,pk,action='complete',global_mode=True)
        return Response(represent(row,request.user))
