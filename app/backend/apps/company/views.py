from apps.orders.production_backend import can_view_production
from apps.employees.order_access import get_order_visibility,OrderVisibility
from io import BytesIO
from PIL import Image
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from apps.directories.permissions import can_view_directories, can_manage_directories, can_manage_suppliers, can_manage_clients
from .models import Company, Organization, AuditEvent
from .serializers import CompanySerializer, OrganizationSerializer, ImageSerializer

@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def session(request):
    return Response({"demo":getattr(settings,"CRM_DEMO_MODE",False), "authenticated": request.user.is_authenticated, "can_view_production":can_view_production(request.user), "can_view_orders":get_order_visibility(request.user)!=OrderVisibility.NONE, "can_view_directories": can_view_directories(request.user), "can_edit_directories": can_manage_directories(request.user), "can_edit_suppliers": can_manage_suppliers(request.user), "can_edit_clients": can_manage_clients(request.user),
        "owner": bool(request.user.is_authenticated and request.user.is_superuser),
        "username": request.user.get_username() if request.user.is_authenticated else "",
        "needs_setup": settings.DEBUG and not get_user_model().objects.exists()})

@method_decorator(csrf_protect, name="dispatch")
class Login(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    def post(self, request):
        user = authenticate(request, username=request.data.get("username", ""), password=request.data.get("password", ""))
        if user is None:
            return Response({"detail": "Неверное имя пользователя или пароль."}, status=400)
        login(request, user)
        return Response({"demo":getattr(settings,"CRM_DEMO_MODE",False), "authenticated": True, "owner": user.is_superuser, "can_view_production":can_view_production(user), "can_view_orders":get_order_visibility(user)!=OrderVisibility.NONE, "can_view_directories": can_view_directories(user), "can_edit_directories": can_manage_directories(user), "can_edit_suppliers": can_manage_suppliers(user), "can_edit_clients": can_manage_clients(user), "username": user.get_username()})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sign_out(request):
    logout(request)
    return Response(status=204)

class Profile(APIView):
    def get(self, request):
        obj, _ = Company.objects.get_or_create(pk=1)
        return Response(CompanySerializer(obj).data)
    def put(self, request):
        obj, _ = Company.objects.get_or_create(pk=1)
        serializer = CompanySerializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditEvent.objects.create(actor=request.user, action="company.updated")
        return Response(serializer.data)

class Organizations(viewsets.ModelViewSet):
    queryset = Organization.objects.filter(is_archived=False)
    serializer_class = OrganizationSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    def perform_create(self, serializer):
        org = serializer.save()
        AuditEvent.objects.create(actor=self.request.user, action="organization.created", organization=org)
    def perform_update(self, serializer):
        org = serializer.save()
        AuditEvent.objects.create(actor=self.request.user, action="organization.updated", organization=org)
    def perform_destroy(self, instance):
        instance.is_archived = True
        instance.save(update_fields=["is_archived", "updated_at"])
        AuditEvent.objects.create(actor=self.request.user, action="organization.archived", organization=instance)

class OrganizationImage(APIView):
    kinds = ["logo", "signature", "stamp"]
    def organization(self, pk, kind):
        if kind not in self.kinds:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        return get_object_or_404(Organization, pk=pk, is_archived=False)
    def get(self, request, pk, kind):
        org = self.organization(pk, kind)
        field = getattr(org, kind)
        if not field:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        response = FileResponse(field.open("rb"), content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        return response
    def post(self, request, pk, kind):
        org = self.organization(pk, kind)
        serializer = ImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["image"]
        with Image.open(file) as image:
            image.load()
            if kind == "logo": image.thumbnail((1024, 1024))
            output = BytesIO()
            image.convert("RGBA").save(output, format="PNG")
        field = getattr(org, kind)
        previous = field.name
        field.save("image.png", ContentFile(output.getvalue()), save=True)
        if previous and previous != field.name: field.storage.delete(previous)
        AuditEvent.objects.create(actor=request.user, action=f"organization.{kind}.uploaded", organization=org)
        return Response(OrganizationSerializer(org).data)
    def delete(self, request, pk, kind):
        org = self.organization(pk, kind)
        getattr(org, kind).delete(save=True)
        AuditEvent.objects.create(actor=request.user, action=f"organization.{kind}.deleted", organization=org)
        return Response(status=status.HTTP_204_NO_CONTENT)

@method_decorator(csrf_protect, name="dispatch")
class InitialSetup(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    def post(self, request):
        # The development server binds to loopback; this endpoint is disabled in production.
        if not settings.DEBUG or request.META.get("REMOTE_ADDR") not in ["127.0.0.1", "::1"]:
            return Response({"detail": "Первичная настройка доступна только локально."}, status=403)
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        User = get_user_model()
        username_field = User._meta.get_field("username")
        user = User(username=username)
        try:
            username_field.clean(username, user)
            validate_password(password, user=user)
        except ValidationError as error:
            return Response({"detail": error.messages}, status=400)
        with transaction.atomic():
            Company.objects.get_or_create(pk=1)
            Company.objects.select_for_update().get(pk=1)
            if User.objects.exists():
                return Response({"detail": "Собственник уже создан. Войдите в CRM."}, status=409)
            user = User.objects.create_superuser(username=username, password=password)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response({"demo":getattr(settings,"CRM_DEMO_MODE",False), "authenticated": True, "owner": True, "username": user.username, "needs_setup": False}, status=201)


class GeneralSettings(APIView):
    permission_classes=[IsAuthenticated]
    fields=['profitability_threshold','show_fully_paid_orders_in_payments','vat_type','vat_percent','designer_own_orders_only','confirm_deletion','quantity_places','money_places','piece_rounding']
    def get(self,request):
        company,_=Company.objects.get_or_create(pk=1)
        return Response({key:getattr(company,key) for key in self.fields})
    def patch(self,request):
        if not request.user.is_superuser:return Response({'detail':'Настройки изменяет только собственник.'},status=403)
        if set(request.data)-set(self.fields):return Response({'detail':'Неизвестная настройка.'},status=400)
        for key,value in request.data.items():
            valid=isinstance(value,bool) if key in ['show_fully_paid_orders_in_payments','confirm_deletion','designer_own_orders_only'] else (value in ['up','nearest'] if key=='piece_rounding' else type(value) is int and 0<=value<=4)
            if key=='profitability_threshold':valid=type(value) is int and 0<=value<=100
            if key=='vat_type':valid=isinstance(value,str) and value in ['none','included']
            if key=='vat_percent':valid=type(value) is int and value in [5,7,20,22]
            if not valid:return Response({key:'Некорректное значение настройки.'},status=400)
        company,_=Company.objects.get_or_create(pk=1)
        for key,value in request.data.items():setattr(company,key,value)
        company.save(update_fields=list(request.data)+['updated_at'])
        return Response({key:getattr(company,key) for key in self.fields})
