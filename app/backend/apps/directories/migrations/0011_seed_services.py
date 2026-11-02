from django.db import migrations

def seed(apps,schema_editor):
    C=apps.get_model('directories','ServiceCategory');S=apps.get_model('directories','Service');U=apps.get_model('directories','MeasureUnit')
    examples=[('Монтаж карнизов',[
        ('Монтаж держателя','Штука',100,250),
        ('Монтаж профильных карнизов','Метр',200,400),
        ('Монтаж шины пластиковой(потолок)','Метр',250,500)]),
        ('Пошив',[
        ('Крой полотна','Метр',100,300),('Московский шов','Метр',50,100),
        ('Обработка края ткани','Метр',30,60),('Отбраковка и декатировка ткани','Метр',50,150),
        ('Пришивание тесьмы','Метр',45,100),('Римская штора','Квадратный метр',750,2000),
        ('Шов с подгибкой (низа, боков)','Метр',30,60)]),
        ('Транспортные услуги',[('Забор/ доставка штор в черте города','Штука',500,1000)])]
    for category,rows in examples:
        c=C.objects.create(name=category)
        for name,unit,work,price in rows:
            S.objects.create(category=c,name=name,name_key=' '.join(name.strip().split()).casefold(),unit=U.objects.get(full_name=unit),work_cost=work,service_price=price)

class Migration(migrations.Migration):
    dependencies=[('directories','0010_servicecategory_service_serviceevent')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
