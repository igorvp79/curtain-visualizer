from django.db import migrations,models

def classify(apps,schema_editor):
    Category=apps.get_model('directories','ServiceCategory')
    for row in Category.objects.filter(parent__isnull=True):
        name=' '.join(row.name.casefold().replace('ё','е').split())
        if name in ['монтаж','монтаж карнизов','доставка','транспортные услуги','замеры','замер']:
            row.participates_in_production=False;row.save(update_fields=['participates_in_production'])

class Migration(migrations.Migration):
    dependencies=[('directories','0019_catalogproduct_proposal_name')]
    operations=[migrations.AddField(model_name='servicecategory',name='participates_in_production',field=models.BooleanField(default=True)),migrations.RunPython(classify,migrations.RunPython.noop)]
