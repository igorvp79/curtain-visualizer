from decimal import Decimal,ROUND_HALF_UP
from django.db import migrations


def backfill(apps,schema_editor):
    Order=apps.get_model('orders','Order');Instance=apps.get_model('orders','OrderInstance')
    Good=apps.get_model('orders','OrderGood');Service=apps.get_model('orders','OrderService');alias=schema_editor.connection.alias
    def rounded(value,places):return value.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
    for order in Order.objects.using(alias).all().iterator():
        discount=Decimal(0)
        for instance in Instance.objects.using(alias).filter(order_id=order.pk,is_active=True):
            for Model in (Good,Service):
                for line in Model.objects.using(alias).filter(instance_id=instance.pk,is_active=True):
                    gross=rounded(line.quantity*line.sale_price,line.money_places)
                    net=rounded(line.quantity*line.sale_price*(1-line.discount/100),line.money_places)
                    discount+=rounded(gross*instance.quantity,line.money_places)-rounded(net*instance.quantity,line.money_places)
        Order.objects.using(alias).filter(pk=order.pk).update(discount_amount=discount)

class Migration(migrations.Migration):
    dependencies=[('orders','0012_instance_adjustments')]
    operations=[migrations.RunPython(backfill,migrations.RunPython.noop)]
