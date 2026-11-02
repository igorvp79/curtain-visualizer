from django.db import migrations


def seed(apps,schema_editor):
    Room=apps.get_model("directories","Room")
    names=['Кухня', 'Гостиная', 'Спальня', 'Детская мальчика', 'Детская девочки', 'Кабинет', 'Ванная', 'Сауна', 'Детская', 'Веранда', 'Холл', 'Коридор', 'Балкон', 'Санузел', 'Лестница', 'Гардеробная', 'Столовая']
    for name in names:
        Room.objects.get_or_create(name_key=name.casefold(),defaults={"name":name})


class Migration(migrations.Migration):
    dependencies=[("directories","0017_room_roomevent")]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
