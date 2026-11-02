from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied,ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import MeasureUnit,UnitEvent,Warehouse,WarehouseEvent,normalize_name
from .serializers import MeasureUnitSerializer,WarehouseSerializer
from .permissions import DirectoryEditor, DirectoryReaderOrEditor

class MeasureUnits(viewsets.ModelViewSet):
    permission_classes=[DirectoryEditor]
    serializer_class=MeasureUnitSerializer
    def get_queryset(self):
        rows=MeasureUnit.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get("search",""))
        if search: rows=rows.filter(Q(name_key__contains=search)|Q(short_key__contains=search))
        ordering=self.request.query_params.get("ordering","id")
        columns={"id":"id","full_name":"name_key","short_name":"short_key"}
        key=ordering.lstrip("-")
        if key not in columns:raise ValidationError("Неверная сортировка.")
        return rows.order_by(("-" if ordering.startswith("-") else "")+columns[key],"id")
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                unit=serializer.save()
                UnitEvent.objects.create(actor=self.request.user,unit=unit,action=action_name)
        except IntegrityError:raise ValidationError({"full_name":"Единица с таким названием уже существует."})
    def perform_create(self,serializer):self.record_save(serializer,"created")
    def perform_update(self,serializer):
        self.record_save(serializer,"updated")
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            UnitEvent.objects.create(actor=self.request.user,unit=instance,action="removed")
    @action(detail=False,methods=["get"],permission_classes=[IsAuthenticated])
    def options(self,request):
        return Response(MeasureUnitSerializer(MeasureUnit.objects.filter(is_active=True),many=True).data)


class Warehouses(viewsets.ModelViewSet):
    permission_classes=[DirectoryEditor]
    serializer_class=WarehouseSerializer
    def get_queryset(self):
        rows=Warehouse.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get("search",""))
        if search:rows=rows.filter(Q(name_key__contains=search)|Q(address_key__contains=search))
        ordering=self.request.query_params.get("ordering","id")
        columns={"id":"id","name":"name_key","address":"address_key"}
        key=ordering.lstrip("-")
        if key not in columns:raise ValidationError("Неверная сортировка.")
        return rows.order_by(("-" if ordering.startswith("-") else "")+columns[key],"id")
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                warehouse=serializer.save()
                WarehouseEvent.objects.create(actor=self.request.user,warehouse=warehouse,action=action_name)
        except IntegrityError:raise ValidationError({"name":"Склад с таким названием уже существует."})
    def perform_create(self,serializer):self.record_save(serializer,"created")
    def perform_update(self,serializer):self.record_save(serializer,"updated")
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            WarehouseEvent.objects.create(actor=self.request.user,warehouse=instance,action="removed")
    @action(detail=False,methods=["get"],permission_classes=[IsAuthenticated])
    def options(self,request):
        return Response(WarehouseSerializer(Warehouse.objects.filter(is_active=True),many=True).data)


from .models import Supplier,SupplierEvent
from .serializers import SupplierSerializer
from .permissions import SupplierEditor
class Suppliers(viewsets.ModelViewSet):
    permission_classes=[SupplierEditor]
    serializer_class=SupplierSerializer
    def get_queryset(self):
        rows=Supplier.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get("search",""))
        if search:rows=rows.filter(search_key__contains=search)
        ordering=self.request.query_params.get("ordering","id")
        columns={"id":"id","name":"name_key"}
        key=ordering.lstrip("-")
        if key not in columns:raise ValidationError("Неверная сортировка.")
        return rows.order_by(("-" if ordering.startswith("-") else "")+columns[key],"id")
    def record_save(self,serializer,action_name):
        with transaction.atomic():
            supplier=serializer.save()
            SupplierEvent.objects.create(actor=self.request.user,supplier=supplier,action=action_name)
    def perform_create(self,serializer):self.record_save(serializer,"created")
    def perform_update(self,serializer):self.record_save(serializer,"updated")
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            SupplierEvent.objects.create(actor=self.request.user,supplier=instance,action="removed")
    @action(detail=False,methods=["get"],permission_classes=[IsAuthenticated])
    def options(self,request):
        return Response(SupplierSerializer(Supplier.objects.filter(is_active=True),many=True).data)


from .models import Client,ClientEvent
from .serializers import ClientSerializer
from .permissions import ClientEditor
from apps.employees.models import Employee
class Clients(viewsets.ModelViewSet):
    permission_classes=[ClientEditor]
    serializer_class=ClientSerializer
    def get_queryset(self):
        user=self.request.user
        rows=Client.objects.filter(is_active=True).select_related('responsible')
        if not user.is_superuser:
            rows=rows.filter(Q(is_private=False)|Q(created_by=user)|Q(responsible__user=user))
            if Employee.objects.filter(user=user,own_clients_only=True).exists():rows=rows.filter(responsible__user=user)
        search=normalize_name(self.request.query_params.get('search',''))
        if search:rows=rows.filter(search_key__contains=search)
        ordering=self.request.query_params.get('ordering','name')
        columns={'name':'name_key','created_at':'created_at'}
        key=ordering.lstrip('-')
        if key not in columns:raise ValidationError('Неверная сортировка.')
        return rows.order_by(('-' if ordering.startswith('-') else '')+columns[key],'id')
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                client=serializer.save(**({'created_by':self.request.user} if not serializer.instance else {}))
                ClientEvent.objects.create(actor=self.request.user,client=client,action=action_name)
        except IntegrityError:raise ValidationError({'phone':'Клиент с таким телефоном уже существует.'})
    def perform_create(self,serializer):self.record_save(serializer,'created')
    def perform_update(self,serializer):self.record_save(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            ClientEvent.objects.create(actor=self.request.user,client=instance,action='removed')
    @action(detail=False,methods=['get'])
    def metadata(self,request):
        rows=Employee.objects.filter(is_blocked=False,user__is_active=True)
        if not request.user.is_superuser and rows.filter(user=request.user,own_clients_only=True).exists():rows=rows.filter(user=request.user)
        employees=[{'id':r.pk,'name':r.full_name} for r in rows if 'manager' in r.roles or 'owner' in r.roles or r.user.is_superuser]
        own=Employee.objects.filter(user=request.user).first()
        return Response({'employees':employees,'default_responsible':own.pk if own else None,'sources':list(ClientSource.objects.filter(is_active=True).values_list('name',flat=True))})


from .models import PriceType,PriceTypeEvent
from .serializers import PriceTypeSerializer
class PriceTypes(viewsets.ModelViewSet):
    permission_classes=[DirectoryEditor]
    serializer_class=PriceTypeSerializer
    def get_queryset(self):
        rows=PriceType.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get('search',''))
        if search:rows=rows.filter(name_key__contains=search)
        ordering=self.request.query_params.get('ordering','id')
        if ordering not in ['id','name','-name']:raise ValidationError('Неверная сортировка.')
        return rows.order_by(ordering.replace('name','name_key'),'id')
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                row=serializer.save();PriceTypeEvent.objects.create(actor=self.request.user,price_type=row,action=action_name)
        except IntegrityError:raise ValidationError({'name':'Тип цены с таким названием уже существует.'})
    def perform_create(self,serializer):self.record_save(serializer,'created')
    def perform_update(self,serializer):self.record_save(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            PriceTypeEvent.objects.create(actor=self.request.user,price_type=instance,action='removed')
    @action(detail=False,methods=['get'],permission_classes=[IsAuthenticated])
    def options(self,request):
        rows=PriceType.objects.filter(is_active=True)
        kind=request.query_params.get('kind')
        if kind=='goods':rows=rows.filter(for_goods=True)
        elif kind=='services':rows=rows.filter(for_services=True)
        elif kind:raise ValidationError('Выберите goods или services.')
        return Response(PriceTypeSerializer(rows,many=True).data)


from .models import CatalogFolder,CatalogProduct
from .serializers import CatalogFolderSerializer,CatalogProductSerializer
class CatalogFolders(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor]
    serializer_class=CatalogFolderSerializer
    queryset=CatalogFolder.objects.all()
    def perform_destroy(self,instance):
        if instance.children.exists() or instance.products.exists():raise ValidationError('Сначала перенесите или удалите содержимое папки.')
        instance.delete()

class CatalogProducts(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor]
    serializer_class=CatalogProductSerializer
    def get_queryset(self):return CatalogProduct.objects.filter(is_active=True)
    def perform_destroy(self,instance):
        instance.is_active=False;instance.save(update_fields=['is_active'])


from .models import ServiceCategory,Service,ServiceEvent
from .serializers import ServiceCategorySerializer,ServiceSerializer
class ServiceCategories(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor]
    serializer_class=ServiceCategorySerializer
    queryset=ServiceCategory.objects.all()
    def perform_destroy(self,instance):
        if instance.children.exists() or instance.services.exists():raise ValidationError('Непустую категорию удалить нельзя. Сначала перенесите её содержимое.')
        instance.delete()

class Services(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor]
    serializer_class=ServiceSerializer
    queryset=Service.objects.filter(is_active=True).select_related('category','unit')
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                row=serializer.save();ServiceEvent.objects.create(actor=self.request.user,service=row,action=action_name)
        except IntegrityError:raise ValidationError({'name':'Услуга с таким наименованием уже существует.'})
    def perform_create(self,serializer):self.record_save(serializer,'created')
    def perform_update(self,serializer):self.record_save(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            ServiceEvent.objects.create(actor=self.request.user,service=instance,action='removed')


from .models import ClientSource,ClientSourceEvent
from .serializers import ClientSourceSerializer
class ClientSources(viewsets.ModelViewSet):
    permission_classes=[DirectoryEditor]
    serializer_class=ClientSourceSerializer
    def get_queryset(self):
        rows=ClientSource.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get('search',''))
        if search:rows=rows.filter(name_key__contains=search)
        ordering=self.request.query_params.get('ordering','id')
        if ordering not in ['id','name','-name']:raise ValidationError('Неверная сортировка.')
        return rows.order_by(ordering.replace('name','name_key'),'id')
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                old=serializer.instance.name if serializer.instance else None
                row=serializer.save()
                if old and old!=row.name:Client.objects.filter(source=old).update(source=row.name)
                ClientSourceEvent.objects.create(actor=self.request.user,source=row,action=action_name)
        except IntegrityError:raise ValidationError({'name':'Источник с таким названием уже существует.'})
    def perform_create(self,serializer):self.record_save(serializer,'created')
    def perform_update(self,serializer):self.record_save(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            ClientSourceEvent.objects.create(actor=self.request.user,source=instance,action='removed')


from .models import Partner,PartnerEvent
from .serializers import PartnerSerializer
class Partners(viewsets.ModelViewSet):
    permission_classes=[ClientEditor]
    serializer_class=PartnerSerializer
    def get_queryset(self):
        user=self.request.user
        rows=Partner.objects.filter(is_active=True).select_related('responsible')
        if not user.is_superuser:
            rows=rows.filter(Q(is_private=False)|Q(created_by=user)|Q(responsible__user=user))
            if Employee.objects.filter(user=user,own_clients_only=True).exists():rows=rows.filter(responsible__user=user)
        search=normalize_name(self.request.query_params.get('search',''))
        if search:rows=rows.filter(search_key__contains=search)
        ordering=self.request.query_params.get('ordering','name')
        columns={'name':'name_key','created_at':'created_at'}
        key=ordering.lstrip('-')
        if key not in columns:raise ValidationError('Неверная сортировка.')
        return rows.order_by(('-' if ordering.startswith('-') else '')+columns[key],'id')
    def record_save(self,serializer,action_name):
        try:
            with transaction.atomic():
                client=serializer.save(**({'created_by':self.request.user} if not serializer.instance else {}))
                PartnerEvent.objects.create(actor=self.request.user,partner=client,action=action_name)
        except IntegrityError:raise ValidationError({'phone':'Партнёр с таким телефоном уже существует.'})
    def perform_create(self,serializer):self.record_save(serializer,'created')
    def perform_update(self,serializer):self.record_save(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            PartnerEvent.objects.create(actor=self.request.user,partner=instance,action='removed')
    @action(detail=False,methods=['get'])
    def metadata(self,request):
        rows=Employee.objects.filter(is_blocked=False,user__is_active=True)
        if not request.user.is_superuser and rows.filter(user=request.user,own_clients_only=True).exists():rows=rows.filter(user=request.user)
        employees=[{'id':r.pk,'name':r.full_name} for r in rows if 'manager' in r.roles or 'owner' in r.roles or r.user.is_superuser]
        own=Employee.objects.filter(user=request.user).first()
        return Response({'employees':employees,'default_responsible':own.pk if own else None,'sources':list(ClientSource.objects.filter(is_active=True).values_list('name',flat=True))})


from .models import Room,RoomEvent
from .serializers import RoomSerializer
class Rooms(viewsets.ModelViewSet):
    permission_classes=[DirectoryEditor]
    serializer_class=RoomSerializer
    def get_queryset(self):
        rows=Room.objects.filter(is_active=True)
        search=normalize_name(self.request.query_params.get('search',''))
        if search:rows=rows.filter(name_key__contains=search)
        ordering=self.request.query_params.get('ordering','id')
        if ordering not in ['id','name','-name']:raise ValidationError('Неверная сортировка.')
        return rows.order_by(ordering.replace('name','name_key'),'id')
    def record(self,serializer,action):
        try:
            with transaction.atomic():
                row=serializer.save();RoomEvent.objects.create(room=row,actor=self.request.user,action=action)
        except IntegrityError:raise ValidationError('Помещение с таким названием уже существует.')
    def perform_create(self,serializer):self.record(serializer,'created')
    def perform_update(self,serializer):self.record(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save()
            RoomEvent.objects.create(room=instance,actor=self.request.user,action='removed')
