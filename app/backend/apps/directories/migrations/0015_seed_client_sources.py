from django.db import migrations
import unicodedata

def seed(apps,schema_editor):
    Source=apps.get_model('directories','ClientSource')
    names=['Клиент салона','Звонок','Сайт','Электронная почта','Яндекс.Директ','Рекомендация дизайнера','Рекомендация от заказчиков']
    for name in names:
        Source.objects.get_or_create(name_key=' '.join(unicodedata.normalize('NFKC',name).strip().split()).casefold(),defaults={'name':name})

class Migration(migrations.Migration):
    dependencies=[('directories','0014_clientsource_clientsourceevent')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
