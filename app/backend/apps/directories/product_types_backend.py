import copy
import re
from decimal import Decimal, DecimalException
from django.db import transaction, IntegrityError
from rest_framework import serializers,viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .permissions import DirectoryEditor, DirectoryReaderOrEditor
from .models import ProductTypeCategory,ProductType,ProductTypeEvent,CatalogProduct,Service,Supplier,ServiceCategory,normalize_name
from .type_calculation import CalculationError,number,parse_formula,evaluate,quantity,money

def validate_configuration(data):
    if not isinstance(data,dict):raise CalculationError('Некорректная настройка типа.')
    result={};names=set()
    for key in ['fields','goods','services','factors']:
        rows=data.get(key,[])
        if not isinstance(rows,list) or len(rows)>100 or any(not isinstance(r,dict) for r in rows):raise CalculationError('В каждом блоке допускается не более 100 строк.')
        result[key]=copy.deepcopy(rows)
    for f in result['fields']:
        name=f.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',name) or name in names:raise CalculationError('Имена переменных: латиница, цифры и _, без повторений, до 40 символов.')
        names.add(name)
        if not isinstance(f.get('label'),str) or not f['label'].strip() or len(f['label'])>150:raise CalculationError('Укажите название каждого вводимого поля (до 150 символов).')
        if f.get('kind') not in ['integer','decimal','list']:raise CalculationError('Неизвестный тип поля.')
        default=number(f.get('default','0'))
        if default<0:raise CalculationError('Значение поля не может быть отрицательным.')
        if f['kind']=='integer' and default!=default.to_integral_value():raise CalculationError('Для целого поля нужно целое значение.')
        if f['kind']=='list':
            opts=f.get('options',[])
            if not isinstance(opts,list) or not 1<=len(opts)<=100:raise CalculationError('Добавьте варианты списка.')
            values=[]
            for option in opts:
                if not isinstance(option,dict) or not str(option.get('label','')).strip():raise CalculationError('У каждого варианта должно быть название.')
                v=number(option.get('value'))
                if v<0 or v in values:raise CalculationError('Значения вариантов должны быть неотрицательными и различаться.')
                values.append(v)
            if default not in values:raise CalculationError('Значение по умолчанию должно быть одним из вариантов списка.')
        if f.get('width',33) not in [8,17,25,33,50,67,75,100]:raise CalculationError('Выберите ширину поля.')
    for key,model in [('goods',CatalogProduct),('services',Service)]:
        for row in result[key]:
            if not isinstance(row.get('item'),int) or isinstance(row.get('item'),bool) or not model.objects.filter(pk=row['item'],is_active=True).exists():raise CalculationError('Выберите действующий товар или услугу в каждой строке.')
            if key=='goods':
                if row.get('supplier') in [None,0,'']:row['supplier']=None
                elif not Supplier.objects.filter(pk=row['supplier'],is_active=True).exists():raise CalculationError('Выбранный поставщик недоступен.')
            parse_formula(row.get('formula',''),names)
    for i,factor in enumerate(result['factors']):
        if not str(factor.get('name','')).strip() or len(str(factor['name']))>150:raise CalculationError('Укажите название надбавки (до 150 символов).')
        if not 0<number(factor.get('percent',0))<=10000:raise CalculationError('Процент надбавки должен быть больше 0, не более 10000.')
        for key in ['default','goods','services']:
            if not isinstance(factor.get(key,False),bool):raise CalculationError('Переключатель должен быть включён или выключен.')
        if not factor.get('goods') and not factor.get('services'):raise CalculationError('Назначьте надбавку товарам или услугам.')
        ids=factor.get('categories',[])
        if not isinstance(ids,list) or any(not isinstance(v,int) for v in ids) or len(set(ids))!=ServiceCategory.objects.filter(pk__in=ids).count():raise CalculationError('Неизвестная категория услуг у надбавки.')
        factor['id']=str(i)
    return result

class TypeCategorySerializer(serializers.ModelSerializer):
    class Meta:model=ProductTypeCategory;fields=['id','name','parent']
    def validate_parent(self,value):
        original=value;seen=set()
        while value:
            if value.pk in seen or self.instance and value.pk==self.instance.pk:raise serializers.ValidationError('Категорию нельзя переместить внутрь самой себя.')
            seen.add(value.pk);value=value.parent
        return original

class ProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model=ProductType
        fields=['id','category','name','configuration','information','proposal_caption']
    def validate_name(self,value):
        rows=ProductType.objects.filter(name_key=normalize_name(value))
        if self.instance:rows=rows.exclude(pk=self.instance.pk)
        if rows.exists():raise serializers.ValidationError('Тип изделия с таким названием уже существует.')
        return value
    def validate_configuration(self,value):
        try:return validate_configuration(value)
        except (CalculationError,TypeError,ValueError) as e:raise serializers.ValidationError(str(e))

class TypeCategories(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor];serializer_class=TypeCategorySerializer;queryset=ProductTypeCategory.objects.all()
    def perform_destroy(self,instance):
        if instance.children.exists() or instance.types.exists():raise ValidationError('Непустую категорию удалить нельзя.')
        instance.delete()

def calculate(template,values,enabled):
    from apps.company.models import Company
    settings,_=Company.objects.get_or_create(pk=1)
    qplaces=settings.quantity_places;mplaces=settings.money_places
    def amount(value):return money(value,mplaces)
    config=validate_configuration(template.configuration)
    if not isinstance(values,dict):raise CalculationError('Значения параметров должны быть объектом.')
    names={f['name'] for f in config['fields']}
    if set(values)-names:raise CalculationError('Передан неизвестный параметр.')
    params={}
    for field in config['fields']:
        value=number(values.get(field['name'],field.get('default',0)))
        if value<0:raise CalculationError(field['label']+': значение не может быть отрицательным.')
        if field['kind']=='integer' and value!=value.to_integral_value():raise CalculationError(field['label']+': нужно целое число.')
        if field['kind']=='list' and value not in [number(o['value']) for o in field['options']]:raise CalculationError(field['label']+': выберите значение из списка.')
        params[field['name']]=value
    if enabled is None:enabled=[f['id'] for f in config['factors'] if f.get('default')]
    if not isinstance(enabled,list) or any(not isinstance(x,str) for x in enabled) or len(enabled)!=len(set(enabled)) or set(enabled)-{f['id'] for f in config['factors']}:raise CalculationError('Неизвестный или повторяющийся коэффициент.')
    goods=[];services=[]
    for key,model,output in [('goods',CatalogProduct,goods),('services',Service,services)]:
        for row in config[key]:
            item=model.objects.get(pk=row['item'])
            unit=item.unit if key=='goods' else item.unit.full_name
            try:qty=quantity(evaluate(row['formula'],params),unit,qplaces,settings.piece_rounding)
            except CalculationError as e:raise CalculationError(item.name+': '+str(e))
            price=item.retail_price if key=='goods' else item.service_price
            cost=item.purchase_price if key=='goods' else item.work_cost
            output.append({'name':item.name,'quantity':str(qty),'unit':unit,'price':str(price),'amount':str(amount(qty*price)),'cost':str(amount(qty*cost)),**({'category':item.category_id} if key=='services' else {'supplier':row['supplier']})})
    goods_sum=sum((number(r['amount']) for r in goods),Decimal(0));service_sum=sum((number(r['amount']) for r in services),Decimal(0));factors=[]
    for f in config['factors']:
        if f['id'] not in enabled:continue
        base=goods_sum if f.get('goods') else Decimal(0)
        if f.get('services'):
            base+=sum((number(r['amount']) for r in services if not f.get('categories') or r['category'] in f['categories']),Decimal(0))
        surcharge=amount(base*number(f['percent'])/100)
        factors.append({'id':f['id'],'name':f['name'],'percent':str(f['percent']),'base':str(base),'amount':str(surcharge)})
    return {'goods':goods,'services':services,'factors':factors,'goods_total':str(amount(goods_sum)),'services_total':str(amount(service_sum)),'total':str(amount(goods_sum+service_sum+sum((number(r['amount']) for r in factors),Decimal(0))))}

class ProductTypes(viewsets.ModelViewSet):
    permission_classes=[DirectoryReaderOrEditor];serializer_class=ProductTypeSerializer;queryset=ProductType.objects.filter(is_active=True)
    def record(self,serializer,action_name):
        try:
            with transaction.atomic():
                row=serializer.save();ProductTypeEvent.objects.create(actor=self.request.user,product_type=row,action=action_name)
        except IntegrityError:raise ValidationError('Тип с таким названием уже существует.')
    def perform_create(self,serializer):self.record(serializer,'created')
    def perform_update(self,serializer):self.record(serializer,'updated')
    def perform_destroy(self,instance):
        with transaction.atomic():
            instance.is_active=False;instance.save();ProductTypeEvent.objects.create(actor=self.request.user,product_type=instance,action='removed')
    @action(detail=True,methods=['post'])
    def copy(self,request,pk=None):
        original=self.get_object();name=original.name[:230]+' Копия';n=2
        while ProductType.objects.filter(name_key=normalize_name(name)).exists():name=original.name[:220]+f' Копия {n}';n+=1
        with transaction.atomic():
            row=ProductType.objects.create(name=name,category=original.category,configuration=copy.deepcopy(original.configuration),information=original.information,proposal_caption=original.proposal_caption)
            ProductTypeEvent.objects.create(actor=request.user,product_type=row,action='copied')
        return Response(self.get_serializer(row).data,status=201)
    @action(detail=True,methods=['post'])
    def preview(self,request,pk=None):
        try:
            template=copy.copy(self.get_object())
            if 'configuration' in request.data:template.configuration=validate_configuration(request.data['configuration'])
            return Response(calculate(template,request.data.get('values',{}),request.data.get('enabled_factors')))
        except DecimalException:raise ValidationError({'detail':'Результат слишком большой или точность расчёта превышена.'})
        except (CalculationError,TypeError,ValueError) as e:raise ValidationError({'detail':str(e)})
