"""Populate template-owned rows atomically; manual rows and historical snapshots are kept."""
import uuid
from decimal import Decimal,DecimalException
from django.db import models
from rest_framework.exceptions import ValidationError
from apps.company.models import Company
from apps.directories.models import CatalogProduct,Service
from apps.directories.type_calculation import evaluate,quantity,money,number,CalculationError
from .models import OrderGood,OrderService,Order


def factors(config):
    # Keys are local to a configuration snapshot, matching the directory editor.
    return [{**f,'id':str(i)} for i,f in enumerate(config.get('factors',[]))]


def populate(instance,user):
    settings,_=Company.objects.get_or_create(pk=1)
    instance.money_places=settings.money_places
    old=list(instance.goods.filter(template_key__isnull=False))
    goods=instance.configuration.get('goods',[])
    services=instance.configuration.get('services',[])
    ids={r['item'] for r in goods}|{r.product_id for r in old}
    # Same lock ordering as manual goods reservation. Caller holds the order lock.
    products={p.pk:p for p in CatalogProduct.objects.select_for_update(of=('self',)).select_related('folder').filter(pk__in=ids).order_by('pk')}
    service_ids={r['item'] for r in services}
    catalogue={s.pk:s for s in Service.objects.select_related('unit','category').filter(pk__in=service_ids)}
    try:
        prepared=[]
        for kind,rules,items in [('goods',goods,products),('services',services,catalogue)]:
            for index,rule in enumerate(rules):
                item=items.get(rule['item'])
                if not item or not item.is_active:raise CalculationError('Товар или услуга из шаблона больше недоступны. Исправьте тип изделия.')
                unit=item.unit if kind=='goods' else item.unit.full_name
                try:qty=quantity(evaluate(rule['formula'],instance.values),unit,settings.quantity_places,settings.piece_rounding)
                except CalculationError as error:raise CalculationError(f'{item.name}: {error}')
                price=item.retail_price if kind=='goods' else item.service_price
                if qty>Decimal('1000000000'):raise CalculationError(f'{item.name}: количество слишком большое.')
                number(qty*price*instance.quantity)
                prepared.append((kind,index,item,qty,unit))
        active_goods=[];active_services=[]
        for kind,index,item,qty,unit in prepared:
            if kind=='goods':
                row=next((r for r in old if r.template_key==index),None)
                same=row and row.product_id==item.pk
                values=dict(product=item,name=item.name,proposal_name=item.proposal_name,article=item.article,category_name=item.folder.name,unit=unit,quantity=qty,purchase_price=item.purchase_price,sale_price=item.retail_price,discount=0,money_places=settings.money_places,is_active=True)
                if row:
                    # Do not transfer an existing hold silently to a different SKU.
                    if not same:values.update(reserve=False,reserve_until=None)
                    for key,value in values.items():setattr(row,key,value)
                    row.save()
                else:row=OrderGood.objects.create(instance=instance,template_key=index,created_by=user,creation_token=uuid.uuid4(),creation_fingerprint='template',**values)
                active_goods.append(row.pk)
            else:
                row=instance.services.filter(template_key=index).first()
                values=dict(service=item,name=item.name,category_id_snapshot=item.category_id,category_name=item.category.name if item.category_id else '',unit=unit,quantity=qty,work_cost=item.work_cost,sale_price=item.service_price,discount=0,money_places=settings.money_places,is_active=True)
                if row:
                    for key,value in values.items():setattr(row,key,value)
                    row.save()
                else:row=OrderService.objects.create(instance=instance,template_key=index,created_by=user,**values)
                active_services.append(row.pk)
        instance.goods.filter(template_key__isnull=False).exclude(pk__in=active_goods).update(is_active=False)
        instance.services.filter(template_key__isnull=False).exclude(pk__in=active_services).update(is_active=False)
        from .goods_backend import ensure_capacity
        # Only validate current CRM holds; an imported baseline may already exceed stock.
        held={r.product_id for r in instance.goods.filter(is_active=True,reserve=True)}
        ensure_capacity([p for p in products.values() if p.pk in held])
        instance.composition_initialized=True
        instance.save(update_fields=['composition_initialized','money_places'])
    except (CalculationError,DecimalException) as error:raise ValidationError({'product_type':str(error)})


def service_amount(row):
    from .layered_adjustments import line_amounts
    return line_amounts(row,'services')['amount']


def service_representation(row,user):
    result=dict(id=row.pk,service=row.service_id,name=row.name,category_name=row.category_name,unit=row.unit,quantity=str(row.quantity),total_quantity=str(row.quantity*row.instance.quantity),sale_price=str(row.sale_price),discount=str(row.discount),complexity=str(row.instance.complexity),amount=str(service_amount(row)),from_template=row.template_key is not None,note=row.note)
    from .layered_adjustments import percentages
    choice=percentages(row,'services')
    result.update(discount=choice['discount'],markup=choice['markup'],inherits_adjustment=choice['inherit'])
    if user.is_superuser:result['work_cost']=str(row.work_cost)
    return result


def summary(instance,user=None,adjustment=None):
    goods=list(instance.goods.filter(is_active=True).select_related('instance'))
    services=list(instance.services.filter(is_active=True).select_related('instance'))
    rule=instance.price_adjustment if adjustment is None else adjustment
    if rule.get('version')==2:
        from .layered_adjustments import calculate
        return calculate(instance,goods,services,rule,user)
    def native_service_amount(row):return money(money(row.quantity*row.sale_price*(Decimal(1)-row.discount/100),row.money_places)*instance.quantity,row.money_places)
    def good_amount(row):return money(money(row.quantity*row.sale_price*(Decimal(1)-row.discount/100),row.money_places)*instance.quantity,row.money_places)
    gsum=sum((good_amount(r) for r in goods),Decimal(0))
    ssum=sum((native_service_amount(r) for r in services),Decimal(0))
    cost=sum((money(money(r.quantity*r.purchase_price,r.money_places)*instance.quantity,r.money_places) for r in goods),Decimal(0))
    # Complexity affects the cost of work, never the material quantity or purchase cost.
    cost+=sum((money(money(r.quantity*r.work_cost*instance.complexity,r.money_places)*instance.quantity,r.money_places) for r in services),Decimal(0))
    additions=[]
    for f in factors(instance.configuration):
        if f['id'] not in instance.enabled_factors:continue
        base=gsum if f.get('goods') else Decimal(0)
        if f.get('services'):
            base+=sum((native_service_amount(r) for r in services if not f.get('categories') or r.category_id_snapshot in f['categories']),Decimal(0))
        value=money(base*number(f['percent'])/100,instance.money_places)
        additions.append(dict(id=f['id'],name=f['name'],percent=str(f['percent']),base=str(base),amount=str(value)))
    total=money(gsum+ssum+sum((Decimal(f['amount']) for f in additions),Decimal(0)),instance.money_places)
    subtotal=total
    from .adjustments_backend import calculate
    change=calculate(instance,subtotal,gsum,ssum,adjustment)
    total=Decimal(change['total'])
    gross=sum((money(money(r.quantity*r.sale_price,r.money_places)*instance.quantity,r.money_places) for r in goods+services),Decimal(0))
    discount_total=gross-gsum-ssum+Decimal(change['discount_amount'])
    number(total);number(cost)
    result=dict(goods_total=str(gsum),services_total=str(ssum),factors=additions,subtotal=str(subtotal),adjustment=change,discount_total=str(discount_total),total=str(total),goods_count=len(goods),services_count=len(services))
    if user is None or user.is_superuser:
        result.update(cost=str(cost),profit=str(total-cost),profit_percent=str(money((total-cost)/total*100,2)) if total else '0.00')
    return result


def update_order(order):
    total=Decimal(0);profit=Decimal(0);discount=Decimal(0)
    try:
        for instance in order.instances.filter(is_active=True):
            result=summary(instance)
            total+=Decimal(result['total']);profit+=Decimal(result['profit']);discount+=Decimal(result['discount_total'])
        number(total);number(profit)
    except (CalculationError,DecimalException) as error:raise ValidationError({'quantity':str(error)})
    order.total_amount=total;order.profit_amount=profit;order.discount_amount=discount
    order.save(update_fields=['total_amount','profit_amount','discount_amount','updated_at'])
