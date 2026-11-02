from django.db import migrations,models
import django.db.models.deletion
class Migration(migrations.Migration):
 dependencies=[('directories','0020_servicecategory_production')]
 operations=[migrations.AlterField(model_name='service',name='category',field=models.ForeignKey(to='directories.servicecategory',on_delete=django.db.models.deletion.PROTECT,related_name='services',null=True,blank=True))]
