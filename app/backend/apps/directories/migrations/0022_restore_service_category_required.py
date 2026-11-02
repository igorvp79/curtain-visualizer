from django.db import migrations,models
import django.db.models.deletion

def preserve(apps,schema_editor):
    Service=apps.get_model('directories','Service');Category=apps.get_model('directories','ServiceCategory')
    rows=Service.objects.filter(category__isnull=True)
    if rows.exists():
        category=Category.objects.filter(name='Общие',parent__isnull=True).first()
        if category is None:category=Category.objects.create(name='Общие',participates_in_production=False)
        rows.update(category=category)

class Migration(migrations.Migration):
    dependencies=[('directories','0021_service_category_optional')]
    operations=[migrations.RunPython(preserve,migrations.RunPython.noop),migrations.AlterField(model_name='service',name='category',field=models.ForeignKey(to='directories.servicecategory',on_delete=django.db.models.deletion.PROTECT,related_name='services'))]
