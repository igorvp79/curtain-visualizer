from rest_framework import serializers
from .models import MeasureUnit,Warehouse,normalize_name

class MeasureUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model=MeasureUnit
        fields=["id","full_name","short_name","is_builtin"]
        read_only_fields=["id","is_builtin"]
        extra_kwargs={"full_name":{"error_messages":{"blank":"Укажите полное наименование."}},"short_name":{"error_messages":{"blank":"Укажите краткое наименование."}}}
    def validate_full_name(self,value):
        units=MeasureUnit.objects.filter(name_key=normalize_name(value))
        if self.instance: units=units.exclude(pk=self.instance.pk)
        if units.exists(): raise serializers.ValidationError("Единица с таким названием уже существует.")
        return value


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model=Warehouse
        fields=["id","name","address"]
        read_only_fields=["id"]
        extra_kwargs={"name":{"error_messages":{"blank":"Укажите наименование склада."}},"address":{"error_messages":{"blank":"Укажите адрес склада."}}}
    def validate_name(self,value):
        rows=Warehouse.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError("Склад с таким названием уже существует.")
        return value


from .models import Supplier
class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model=Supplier
        fields=["id","name","phone","email","manager_name","inn","note"]
        read_only_fields=["id"]
        extra_kwargs={"name":{"error_messages":{"blank":"Укажите наименование поставщика."}}}
    def validate_inn(self,value):
        if value and (len(value) not in [10,12] or not value.isascii() or not value.isdigit()):
            raise serializers.ValidationError("ИНН должен содержать 10 или 12 цифр.")
        return value


from .models import Client,normalize_phone
from apps.employees.models import Employee
class ClientSerializer(serializers.ModelSerializer):
    full_name=serializers.SerializerMethodField()
    responsible_name=serializers.CharField(source='responsible.full_name',read_only=True)
    class Meta:
        model=Client
        fields=['kind','organization_name','inn','kpp','contact_name','legal_address','account_number','bank_name','bank_bik','correspondent_account','id','surname','first_name','patronymic','full_name','phone','email','address','note','source','responsible','responsible_name','is_private','created_at']
        read_only_fields=['id','created_at']
        extra_kwargs={
            'surname':{'required':False,'allow_blank':True},
            'first_name':{'required':False,'allow_blank':True},
            'phone':{'required':True,'allow_blank':False,'error_messages':{'required':'Укажите телефон.','blank':'Укажите телефон.'}},
            'address':{'required':True,'allow_blank':False,'error_messages':{'required':'Укажите адрес.','blank':'Укажите адрес.'}},
        }
    def get_full_name(self,obj):return obj.organization_name if obj.kind=='legal' else ' '.join(filter(None,[obj.surname,obj.first_name,obj.patronymic]))
    def validate(self,data):
        kind=data.get('kind',getattr(self.instance,'kind','person'))
        errors={}
        required={'organization_name':'наименование организации','inn':'ИНН'} if kind=='legal' else {'surname':'фамилию','first_name':'имя'}
        for key,label in required.items():
            if (not self.partial or key in data or 'kind' in data) and not data.get(key,getattr(self.instance,key,'')):
                errors[key]=f'Укажите {label}.'
        if kind=='legal':
            for key,lengths in {'inn':(10,12),'kpp':(9,),'account_number':(20,),'bank_bik':(9,),'correspondent_account':(20,)}.items():
                value=data.get(key,getattr(self.instance,key,''))
                if value and (len(value) not in lengths or not value.isascii() or not value.isdigit()):
                    errors[key]='Укажите '+ ' или '.join(str(n) for n in lengths)+' цифр.'
        if errors:raise serializers.ValidationError(errors)
        return data
    def validate_phone(self,value):
        key=normalize_phone(value)
        if not 6<=len(key)<=15:raise serializers.ValidationError('Укажите действительный номер телефона.')
        rows=Client.objects.filter(phone_key=key)
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Клиент с таким телефоном уже существует.')
        return value
    def validate_responsible(self,value):
        if value.is_blocked or not value.user_id or not value.user.is_active or not ('manager' in value.roles or 'owner' in value.roles or value.user.is_superuser):
            raise serializers.ValidationError('Выберите активного собственника или дизайнера.')
        request=self.context.get('request')
        if request and not request.user.is_superuser:
            own=Employee.objects.filter(user=request.user,own_clients_only=True).exists()
            if own and value.user_id!=request.user.pk:raise serializers.ValidationError('Можно назначить только себя.')
        return value


from .models import PriceType
class PriceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model=PriceType
        fields=['id','name','for_goods','for_services','is_base']
        read_only_fields=['id','is_base']
    def validate_name(self,value):
        rows=PriceType.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Тип цены с таким названием уже существует.')
        return value
    def validate(self,data):
        if self.instance and self.instance.is_base and (data.get('for_goods') is False or data.get('for_services') is False):
            raise serializers.ValidationError('Базовый тип цены применяется к товарам и услугам.')
        return data


from .models import CatalogFolder,CatalogProduct
class CatalogFolderSerializer(serializers.ModelSerializer):
    class Meta:model=CatalogFolder;fields=['id','name','parent']
    def validate_parent(self,value):
        seen=set()
        while value:
            if value.pk in seen or (self.instance and value.pk==self.instance.pk):raise serializers.ValidationError('Нельзя переместить папку внутрь неё самой.')
            seen.add(value.pk);value=value.parent
        return self.initial_data.get('parent') and CatalogFolder.objects.get(pk=self.initial_data['parent']) or None

class CatalogProductSerializer(serializers.ModelSerializer):
    available=serializers.SerializerMethodField()
    class Meta:
        model=CatalogProduct
        fields=['id','folder','source_code','article','name','proposal_name','unit','supplier','retail_price','purchase_price','stock','reserved','available']
        read_only_fields=['stock','reserved','available']
    def crm_reserved(self):
        if '_crm_reserved' not in self.context:
            from apps.orders.goods_backend import reserved_totals
            self.context['_crm_reserved']=reserved_totals()
        return self.context['_crm_reserved']
    def get_available(self,obj):
        from decimal import Decimal
        return str(max(Decimal(0),obj.stock-obj.reserved-self.crm_reserved().get(obj.pk,Decimal(0))))
    def to_representation(self,obj):
        from decimal import Decimal
        result=super().to_representation(obj)
        result['reserved']=str(obj.reserved+self.crm_reserved().get(obj.pk,Decimal(0)))
        return result
    def validate(self,data):
        if data.get('retail_price',0)<0 or data.get('purchase_price',0)<0:raise serializers.ValidationError('Цена не может быть отрицательной.')
        return data


from .models import ServiceCategory,Service
class ServiceCategorySerializer(serializers.ModelSerializer):
    effective_production=serializers.SerializerMethodField()
    class Meta:model=ServiceCategory;fields=['id','name','parent','participates_in_production','effective_production']
    def get_effective_production(self,obj):
        from .production_categories import production_map
        if 'production_map' not in self.context:self.context['production_map']=production_map()
        return self.context['production_map'].get(obj.pk,True)
    def validate_parent(self,value):
        original=value;seen=set()
        while value:
            if value.pk in seen or (self.instance and value.pk==self.instance.pk):raise serializers.ValidationError('Нельзя переместить категорию внутрь себя.')
            seen.add(value.pk);value=value.parent
        return original

class ServiceSerializer(serializers.ModelSerializer):
    unit_name=serializers.CharField(source='unit.short_name',read_only=True)
    category_name=serializers.CharField(source='category.name',read_only=True)
    class Meta:
        model=Service
        fields=['id','category','category_name','name','unit','unit_name','work_cost','service_price','created_at']
        read_only_fields=['id','created_at']
    def validate_name(self,value):
        rows=Service.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Услуга с таким наименованием уже существует.')
        return value
    def validate_unit(self,value):
        if not value.is_active:raise serializers.ValidationError('Выберите действующую единицу измерения.')
        return value
    def validate(self,data):
        if data.get('work_cost',0)<0 or data.get('service_price',0)<0:raise serializers.ValidationError('Стоимость не может быть отрицательной.')
        return data


from .models import ClientSource
class ClientSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model=ClientSource
        fields=['id','name']
    def validate_name(self,value):
        rows=ClientSource.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Источник с таким названием уже существует.')
        return value


from .models import Partner
class PartnerSerializer(serializers.ModelSerializer):
    full_name=serializers.SerializerMethodField()
    responsible_name=serializers.CharField(source='responsible.full_name',read_only=True)
    class Meta:
        model=Partner
        fields=['kind','organization_name','inn','kpp','contact_name','legal_address','account_number','bank_name','bank_bik','correspondent_account','id','surname','first_name','patronymic','full_name','phone','email','address','note','source','responsible','responsible_name','is_private','created_at']
        read_only_fields=['id','created_at']
        extra_kwargs={
            'surname':{'required':False,'allow_blank':True},
            'first_name':{'required':False,'allow_blank':True},
            'phone':{'required':True,'allow_blank':False,'error_messages':{'required':'Укажите телефон.','blank':'Укажите телефон.'}},
            'address':{'required':True,'allow_blank':False,'error_messages':{'required':'Укажите адрес.','blank':'Укажите адрес.'}},
        }
    def get_full_name(self,obj):return obj.organization_name if obj.kind=='legal' else ' '.join(filter(None,[obj.surname,obj.first_name,obj.patronymic]))
    def validate(self,data):
        kind=data.get('kind',getattr(self.instance,'kind','person'))
        errors={}
        required={'organization_name':'наименование организации','inn':'ИНН'} if kind=='legal' else {'surname':'фамилию','first_name':'имя'}
        for key,label in required.items():
            if (not self.partial or key in data or 'kind' in data) and not data.get(key,getattr(self.instance,key,'')):
                errors[key]=f'Укажите {label}.'
        if kind=='legal':
            for key,lengths in {'inn':(10,12),'kpp':(9,),'account_number':(20,),'bank_bik':(9,),'correspondent_account':(20,)}.items():
                value=data.get(key,getattr(self.instance,key,''))
                if value and (len(value) not in lengths or not value.isascii() or not value.isdigit()):
                    errors[key]='Укажите '+ ' или '.join(str(n) for n in lengths)+' цифр.'
        if errors:raise serializers.ValidationError(errors)
        return data
    def validate_phone(self,value):
        key=normalize_phone(value)
        if not 6<=len(key)<=15:raise serializers.ValidationError('Укажите действительный номер телефона.')
        rows=Partner.objects.filter(phone_key=key)
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Партнёр с таким телефоном уже существует.')
        return value
    def validate_responsible(self,value):
        if value.is_blocked or not value.user_id or not value.user.is_active or not ('manager' in value.roles or 'owner' in value.roles or value.user.is_superuser):
            raise serializers.ValidationError('Выберите активного собственника или дизайнера.')
        request=self.context.get('request')
        if request and not request.user.is_superuser:
            own=Employee.objects.filter(user=request.user,own_clients_only=True).exists()
            if own and value.user_id!=request.user.pk:raise serializers.ValidationError('Можно назначить только себя.')
        return value


from .models import Room
class RoomSerializer(serializers.ModelSerializer):
    class Meta:model=Room;fields=['id','name']
    def validate_name(self,value):
        rows=Room.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Помещение с таким названием уже существует.')
        return value
