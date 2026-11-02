from rest_framework.permissions import BasePermission
class IsOwner(BasePermission):
    message = "Раздел доступен только собственнику."
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_active and request.user.is_superuser)
