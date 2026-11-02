from django.db import migrations

def seed(apps,schema_editor):
    P=apps.get_model('directories','PriceType')
    P.objects.get_or_create(name_key='цена продажи',defaults={'name':'Цена продажи','is_base':True,'for_goods':True,'for_services':True})
    P.objects.get_or_create(name_key='цена закупа',defaults={'name':'Цена закупа','for_goods':True,'for_services':True})

class Migration(migrations.Migration):
    dependencies=[('directories','0007_pricetype_pricetypeevent')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
