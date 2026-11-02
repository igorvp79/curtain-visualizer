from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from .models import Employee, EmployeeEvent
from .serializers import EmployeeSerializer, PinSerializer, OwnProfileSerializer
from .roles import ROLES

def ensure_profiles():
    from django.contrib.auth import get_user_model
    for user in get_user_model().objects.filter(employee__isnull=True):
        Employee.objects.get_or_create(user=user, defaults={"full_name": user.get_full_name() or user.username,
            "roles": ["owner"] if user.is_superuser else ["manager"], "is_blocked": not user.is_active})

class Employees(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    def get_queryset(self):
        ensure_profiles()
        qs = Employee.objects.select_related("user")
        if self.action != "list": return qs
        kind = self.request.query_params.get("kind", "staff")
        state = self.request.query_params.get("status", "active")
        if kind not in ["staff", "contractor", "all"] or state not in ["active", "blocked", "all"]:
            raise ValidationError("Неверный отбор списка сотрудников.")
        if kind != "all": qs = qs.filter(kind=kind)
        if state != "all": qs = qs.filter(is_blocked=state == "blocked")
        search = self.request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(full_name__icontains=search) | Q(user__username__icontains=search) | Q(phone__icontains=search) | Q(email__icontains=search))
        return qs
    def perform_create(self, serializer):
        employee = serializer.save()
        EmployeeEvent.objects.create(actor=self.request.user, employee=employee, action="created")
    def perform_update(self, serializer):
        employee = serializer.save()
        EmployeeEvent.objects.create(actor=self.request.user, employee=employee, action="updated")
    @action(detail=False, methods=["get"])
    def metadata(self, request):
        return Response({"roles": [{"value": k, "label": v} for k, v in ROLES.items()],
            "timezones": ["Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "UTC"]})
    @action(detail=True, methods=["post"])
    def pin(self, request, pk=None):
        employee = self.get_object()
        if not employee.user_id: raise ValidationError("У подрядчика нет ПИН-кода.")
        serializer = PinSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            employee.user.set_password(serializer.validated_data["pin"])
            employee.user.save(update_fields=["password"])
            EmployeeEvent.objects.create(actor=request.user, employee=employee, action="pin_changed")
        if employee.user_id == request.user.pk: update_session_auth_hash(request, employee.user)
        return Response({"detail": "ПИН-код изменён."})

class OwnProfile(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        ensure_profiles()
        obj = request.user.employee
        return Response(EmployeeSerializer(obj).data)
    def put(self, request):
        ensure_profiles()
        obj = request.user.employee
        serializer = OwnProfileSerializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True); serializer.save()
        EmployeeEvent.objects.create(actor=request.user, employee=obj, action="profile_updated")
        return Response(EmployeeSerializer(obj).data)


class EmployeeAvatar(APIView):
    permission_classes = [IsAuthenticated]
    def employee(self, request, pk):
        from django.shortcuts import get_object_or_404
        from rest_framework.exceptions import PermissionDenied
        employee = get_object_or_404(Employee, pk=pk)
        if not request.user.is_superuser and employee.user_id != request.user.pk:
            raise PermissionDenied("Нет доступа к фотографии сотрудника.")
        return employee
    def get(self, request, pk):
        from django.http import FileResponse
        from rest_framework.exceptions import NotFound
        employee = self.employee(request, pk)
        if not employee.avatar: raise NotFound()
        response = FileResponse(employee.avatar.open("rb"), content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        return response
    def post(self, request, pk):
        from io import BytesIO
        from PIL import Image, ImageOps
        from django.core.files.base import ContentFile
        from apps.company.serializers import ImageSerializer
        employee = self.employee(request, pk)
        serializer = ImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["image"]
        if file.size > 500 * 1024: raise ValidationError({"image": "Фото должно быть не больше 500 КБ."})
        with Image.open(file) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((512, 512))
            output = BytesIO(); image.convert("RGBA").save(output, "PNG")
        previous = employee.avatar.name
        employee.avatar.save("avatar.png", ContentFile(output.getvalue()), save=True)
        if previous and previous != employee.avatar.name: employee.avatar.storage.delete(previous)
        EmployeeEvent.objects.create(actor=request.user, employee=employee, action="avatar_uploaded")
        return Response(EmployeeSerializer(employee).data)
    def delete(self, request, pk):
        employee = self.employee(request, pk)
        employee.avatar.delete(save=True)
        EmployeeEvent.objects.create(actor=request.user, employee=employee, action="avatar_removed")
        return Response(EmployeeSerializer(employee).data)
