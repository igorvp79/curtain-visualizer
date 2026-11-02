"""Independent goods/services percentages, then general percentages, then rubles."""
import copy
from decimal import Decimal
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from apps.directories.type_calculation import money,number


def defaults():
    return {'version':2,'goods':{'discount':'0','markup':'0','rows':{}},'services':{'discount':'0','markup':'0','rows':{}},'general':{'discount':'0','markup':'0','correction':'0'}}

class StrictInput(serializers.Serializer):
    def to_internal_value(self,data):
        if not isinstance(data,dict):raise ValidationError('Ожидается объект настроек.')
        extra=set(data)-set(self.fields)
        if extra:raise ValidationError({key:'Неизвестное поле настройки.' for key in extra})
        return super().to_internal_value(data)

class PercentInput(StrictInput):
    discount=serializers.DecimalField(max_digits=6,decimal_places=2,min_value=Decimal(0),max_value=Decimal(100))
    markup=serializers.DecimalField(max_digits=6,decimal_places=2,min_value=Decimal(0),max_value=Decimal(1000))

class RowInput(PercentInput):
    inherit=serializers.BooleanField()

class GroupInput(PercentInput):
    rows=serializers.DictField(child=RowInput())
    def validate_rows(self,value):
        if len(value)>2000 or any(not key.isascii() or not key.isdigit() or len(key)>20 or str(int(key))!=key or int(key)<=0 for key in value):raise ValidationError('Некорректный список позиций.')
        return value

class GeneralInput(PercentInput):
    correction=serializers.DecimalField(max_digits=18,decimal_places=4,min_value=Decimal('-1000000000'),max_value=Decimal('1000000000'))

class LayeredInput(StrictInput):
    version=serializers.IntegerField(min_value=2,max_value=2)
    goods=GroupInput()
    services=GroupInput()
    general=GeneralInput()
    def validate(self,data):
        def strings(value):
            if isinstance(value,Decimal):return str(value)
            if isinstance(value,dict):return {key:strings(item) for key,item in value.items()}
            return value
        return strings(data)


def validate_rows(instance,rule):
    for kind in ('goods','services'):
        known={str(pk) for pk in getattr(instance,kind).filter(is_active=True).values_list('pk',flat=True)}
        if set(rule[kind]['rows'])-known:raise ValidationError({kind:'Список позиций изменился. Закройте окно и откройте его заново.'})


def percentages(row,kind,rule=None):
    rule=row.instance.price_adjustment if rule is None else rule
    if rule.get('version')!=2:return {'discount':str(row.discount),'markup':'0','inherit':False}
    group=rule[kind]
    own=group['rows'].get(str(row.pk))
    if own is not None:
        source=group if own['inherit'] else own
        return {'discount':source['discount'],'markup':source['markup'],'inherit':own['inherit']}
    if row.discount!=0:return {'discount':str(row.discount),'markup':'0','inherit':False}
    return {'discount':group['discount'],'markup':group['markup'],'inherit':True}


def line_amounts(row,kind,rule=None):
    choice=percentages(row,kind,rule)
    gross=money(row.quantity*row.sale_price,row.money_places)
    # A line has one pair of percentages: its own pair replaces the group's pair.
    applied=row.instance.price_adjustment if rule is None else rule
    if applied.get('version')==2:
        discount=money(gross*Decimal(choice['discount'])/100,row.money_places)
        markup=money(gross*Decimal(choice['markup'])/100,row.money_places)
        amount=money(gross+markup-discount,row.money_places)
    else:
        amount=money(row.quantity*row.sale_price*(1-row.discount/100),row.money_places)
        discount=gross-amount;markup=Decimal(0)
    n=row.instance.quantity
    return {**choice,'gross':money(gross*n,row.money_places),'discount_amount':money(discount*n,row.money_places),'markup_amount':money(markup*n,row.money_places),'amount':money(amount*n,row.money_places)}


def sync_line_discount(instance,row,kind,values):
    if instance.price_adjustment.get('version')!=2:return
    row.instance=instance
    current=percentages(row,kind)
    if Decimal(values['discount'])==Decimal(current['discount']):
        # Keeping the effective percentage must not turn an inherited row into an override.
        values['discount']=row.discount
        return
    rule=copy.deepcopy(instance.price_adjustment)
    rule[kind]['rows'][str(row.pk)]={'inherit':False,'discount':str(values['discount']),'markup':current['markup']}
    instance.price_adjustment=rule;instance.save(update_fields=['price_adjustment','updated_at'])
    row.instance=instance


def calculate(instance,goods,services,rule,user=None):
    from .composition_backend import factors
    result={'goods':{},'services':{}}
    cost=Decimal(0);line_discount=Decimal(0);line_markup=Decimal(0)
    for kind,rows in [('goods',goods),('services',services)]:
        total=Decimal(0);discount=Decimal(0);markup=Decimal(0);details=[]
        for row in rows:
            row.instance=instance
            values=line_amounts(row,kind,rule)
            total+=values['amount'];discount+=values['discount_amount'];markup+=values['markup_amount']
            unit_cost=row.purchase_price if kind=='goods' else row.work_cost*instance.complexity
            cost+=money(money(row.quantity*unit_cost,row.money_places)*instance.quantity,row.money_places)
            details.append({'id':row.pk,'name':row.name,'unit':row.unit,'quantity':str(row.quantity),'total_quantity':str(row.quantity*instance.quantity),'sale_price':str(row.sale_price),'discount':values['discount'],'markup':values['markup'],'inherit':values['inherit'],'gross':str(values['gross']),'amount':str(values['amount'])})
        result[kind]={'base':str(total+discount-markup),'total':str(total),'discount_amount':str(discount),'markup_amount':str(markup),'rows':details}
        line_discount+=discount;line_markup+=markup
    additions=[]
    for factor in factors(instance.configuration):
        if factor['id'] not in instance.enabled_factors:continue
        base=Decimal(result['goods']['total']) if factor.get('goods') else Decimal(0)
        if factor.get('services'):
            base+=sum((line_amounts(row,'services',rule)['amount'] for row in services if not factor.get('categories') or row.category_id_snapshot in factor['categories']),Decimal(0))
        value=money(base*Decimal(str(factor['percent']))/100,instance.money_places)
        additions.append({'id':factor['id'],'name':factor['name'],'percent':str(factor['percent']),'base':str(base),'amount':str(value)})
    subtotal=money(Decimal(result['goods']['total'])+Decimal(result['services']['total'])+sum((Decimal(f['amount']) for f in additions),Decimal(0)),instance.money_places)
    general=rule['general']
    gd=money(subtotal*Decimal(general['discount'])/100,instance.money_places)
    gm=money(subtotal*Decimal(general['markup'])/100,instance.money_places)
    percent_total=money(subtotal+gm-gd,instance.money_places)
    requested=money(Decimal(general['correction']),instance.money_places)
    correction=max(-percent_total,requested) if subtotal>0 else Decimal(0)
    total=money(percent_total+correction,instance.money_places)
    number(total);number(cost)
    clean=copy.deepcopy(rule)
    # Do not keep removed row IDs in the editor payload.
    for kind in ('goods','services'):
        live={str(row['id']) for row in result[kind]['rows']}
        clean[kind]['rows']={key:value for key,value in clean[kind]['rows'].items() if key in live}
    active=any(Decimal(rule[kind][key])!=0 for kind in ('goods','services','general') for key in ('discount','markup')) or Decimal(general['correction'])!=0 or any(Decimal(row['discount'])!=0 or Decimal(row['markup'])!=0 for kind in ('goods','services') for row in result[kind]['rows'])
    adjustment={'version':2,'rule':clean,'groups':result,'general':{**general,'base':str(subtotal),'discount_amount':str(gd),'markup_amount':str(gm),'percent_total':str(percent_total),'correction_amount':str(correction),'correction_limited':correction!=requested},'active':active,'discount_amount':str(line_discount+gd+max(Decimal(0),-correction)),'markup_amount':str(line_markup+gm+max(Decimal(0),correction)),'discount_limited':correction!=requested,'markup_limited':False,'total':str(total)}
    response={'goods_total':result['goods']['total'],'services_total':result['services']['total'],'factors':additions,'factors_total':str(sum((Decimal(f['amount']) for f in additions),Decimal(0))),'subtotal':str(subtotal),'adjustment':adjustment,'discount_total':adjustment['discount_amount'],'total':str(total),'goods_count':len(goods),'services_count':len(services)}
    if user is None or user.is_superuser:response.update(cost=str(cost),profit=str(total-cost),profit_percent=str(money((total-cost)/total*100,2)) if total else '0.00')
    return response


def editor_summary(instance,user):
    from .composition_backend import summary
    if instance.price_adjustment.get('version')==2:return summary(instance,user)
    rule=defaults();old=instance.price_adjustment
    if old:
        scope=old.get('scope','all');target=rule['general'] if scope=='all' else rule[scope]
        for key in ('discount','markup'):
            if old.get(key+'_kind')=='percent':target[key]=str(money(Decimal(old.get(key+'_value','0')),2))
            else:rule['general']['correction']=str(Decimal(rule['general']['correction'])+Decimal(old.get(key+'_value','0'))*(-1 if key=='discount' else 1))
    # Seed existing individual line discounts as explicit overrides in the editor.
    for kind in ('goods','services'):
        for row in getattr(instance,kind).filter(is_active=True):
            if row.discount!=0:rule[kind]['rows'][str(row.pk)]={'inherit':False,'discount':str(row.discount),'markup':'0'}
    before=summary(instance,user)
    suggested=summary(instance,user,adjustment=rule)
    rule['general']['correction']=str(Decimal(rule['general']['correction'])+Decimal(before['total'])-Decimal(suggested['total']))
    response=summary(instance,user,adjustment=rule)
    response['legacy_converted']=bool(old)
    return response
