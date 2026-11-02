from rest_framework.permissions import BasePermission

def can_manage_directories(user):
    if not user.is_authenticated or not user.is_active: return False
    if user.is_superuser: return True
    from apps.employees.models import Employee
    return any("directory_editor" in roles for roles in Employee.objects.filter(user=user,is_blocked=False).values_list("roles",flat=True))

class DirectoryEditor(BasePermission):
    message = "Справочник доступен собственнику и редактору справочников."
    def has_permission(self, request, view): return can_manage_directories(request.user)


def can_manage_suppliers(user):
    if can_manage_directories(user):return True
    if not user.is_authenticated or not user.is_active:return False
    from apps.employees.models import Employee
    return any("procurement" in roles for roles in Employee.objects.filter(user=user,is_blocked=False).values_list("roles",flat=True))

class SupplierEditor(BasePermission):
    message="Поставщики доступны собственнику, редактору справочников и комплектовщику."
    def has_permission(self,request,view):return can_manage_suppliers(request.user)


def can_manage_clients(user):
    if not user.is_authenticated or not user.is_active:return False
    if user.is_superuser:return True
    from apps.employees.models import Employee
    return any('manager' in roles for roles in Employee.objects.filter(user=user,is_blocked=False).values_list('roles',flat=True))

class ClientEditor(BasePermission):
    message='Клиенты доступны собственнику и менеджеру.'
    def has_permission(self,request,view):return can_manage_clients(request.user)


def can_view_directories(user):
    if can_manage_directories(user):return True
    if not user.is_authenticated or not user.is_active:return False
    from apps.employees.models import Employee
    return any('manager' in roles for roles in Employee.objects.filter(user=user,is_blocked=False).values_list('roles',flat=True))

class DirectoryReaderOrEditor(BasePermission):
    message='Просмотр справочников доступен дизайнеру, изменение — собственнику и редактору справочников.'
    def has_permission(self,request,view):
        return can_view_directories(request.user) if request.method in ('GET','HEAD','OPTIONS') else can_manage_directories(request.user)
