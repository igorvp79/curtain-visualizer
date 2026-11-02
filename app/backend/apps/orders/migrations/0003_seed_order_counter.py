from django.db import migrations
import re

def seed(apps,schema_editor):
    Order=apps.get_model('orders','Order')
    Counter=apps.get_model('orders','OrderNumberCounter')
    maximum=0
    for row in Order.objects.all().iterator():
        maximum=max(maximum,row.sequence_number or 0)
        match=re.search(r'-(\d+)$',row.number)
        if match:maximum=max(maximum,int(match.group(1)))
    Counter.objects.get_or_create(pk=1,defaults={'next_number':maximum+1})

class Migration(migrations.Migration):
    dependencies=[('orders','0002_ordernumbercounter_order_creation_fingerprint_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
