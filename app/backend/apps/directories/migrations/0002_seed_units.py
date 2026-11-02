from django.db import migrations
import unicodedata

UNITS = [
    ("Метр", "м."), ("Штука", "шт."), ("Квадратный метр", "кв. м."), ("Килограмм", "кг."),
    ("Рулон", "рул."), ("Погонный метр", "п. м."), ("Комплект", "комп."), ("Километр", "км."),
    ("Секция", "сек."), ("Час", "ч."), ("Сантиметр", "см."), ("Миллиметр", "мм."),
    ("Кронштейн", "крон."), ("Литр", "л."), ("Пара", "пара"), ("Этаж", "эт."),
    ("Квадратный дециметр", "кв. дм."),
]
def normalized(value): return " ".join(unicodedata.normalize("NFKC",value).split()).casefold()
def seed(apps,schema_editor):
    Unit=apps.get_model("directories","MeasureUnit")
    for full,short in UNITS:
        Unit.objects.get_or_create(name_key=normalized(full),defaults={"full_name":full,"short_name":short,"short_key":normalized(short),"is_builtin":True})
    Unit.objects.get_or_create(name_key="купон",defaults={"full_name":"Купон","short_name":"купон","short_key":"купон","is_builtin":False})

class Migration(migrations.Migration):
    dependencies=[("directories","0001_initial")]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
