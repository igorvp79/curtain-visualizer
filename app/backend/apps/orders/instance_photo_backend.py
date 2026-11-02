from io import BytesIO
import uuid,warnings
from PIL import Image,ImageOps,UnidentifiedImageError
from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework.exceptions import ValidationError,PermissionDenied
from .models import Order,OrderEvent

def upload(order,instance,user,file):
    from .views import can_edit_order
    if not can_edit_order(user,order):raise PermissionDenied('Недостаточно прав для изменения фотографии.')
    if not file:raise ValidationError('Выберите фотографию.')
    if file.size>10*1024*1024:raise ValidationError('Фотография должна быть не больше 10 МБ.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(file) as image:
                if image.format not in ['JPEG','PNG','WEBP']:raise ValidationError('Выберите фотографию JPG, PNG или WebP.')
                if image.width*image.height>20000000:raise ValidationError('Фотография слишком большая. Максимум — 20 мегапикселей.')
                image.load();image=ImageOps.exif_transpose(image);image.thumbnail((2400,2400))
                if image.mode in ['RGBA','LA'] or 'transparency' in image.info:
                    rgba=image.convert('RGBA');background=Image.new('RGB',rgba.size,'white');background.paste(rgba,mask=rgba.getchannel('A'));image=background
                output=BytesIO();image.convert('RGB').save(output,'JPEG',quality=90)
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombWarning,Image.DecompressionBombError):raise ValidationError('Не удалось прочитать фотографию. Выберите другой файл.')
    storage=instance.photo.storage;new_name=None
    try:
        with transaction.atomic():
            current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
            if not can_edit_order(user,current):raise PermissionDenied('Недостаточно прав для изменения фотографии.')
            row=current.instances.select_for_update().get(pk=instance.pk,is_active=True)
            previous=row.photo.name
            row.photo.save(uuid.uuid4().hex+'.jpg',ContentFile(output.getvalue()),save=False);new_name=row.photo.name
            row.save(update_fields=['photo'])
            OrderEvent.objects.create(order=current,actor=user,action='instance_photo_uploaded',details={'instance_id':row.pk})
            if previous:transaction.on_commit(lambda:storage.delete(previous))
        return row
    except Exception:
        if new_name:storage.delete(new_name)
        raise
