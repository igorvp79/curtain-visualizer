from pathlib import PurePosixPath
import hashlib,uuid
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError,PermissionDenied,NotFound
from .models import Order,OrderInstanceDocument,OrderEvent

MAX_SIZE=100*1024*1024

def preview_type(document):
    try:
        with document.file.open('rb') as source:header=source.read(32)
    except FileNotFoundError:return None
    if header.startswith(b'%PDF-'):return 'application/pdf'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if header.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if header[:6] in [b'GIF87a',b'GIF89a']:return 'image/gif'
    if header[:4]==b'RIFF' and header[8:12]==b'WEBP':return 'image/webp'
    from .office_preview import office_kind
    if header.startswith(b'PK') and office_kind(document):return 'text/html'
    return None


def represent(row):
    mime=preview_type(row)
    return {'preview_kind':'pdf' if mime=='application/pdf' else 'document' if mime=='text/html' else 'image' if mime else None,'preview_url':f'/api/orders/{row.instance.order_id}/instances/{row.instance_id}/documents/{row.pk}/?preview=1' if mime else None,'task_category':row.task_category,'id':row.pk,'name':row.name,'size':row.size,'created_at':row.created_at,'download_url':f'/api/orders/{row.instance.order_id}/instances/{row.instance_id}/documents/{row.pk}/'}

def upload(order,instance,user,file,token,category=None):
    from .views import can_edit_order
    if not can_edit_order(user,order):raise PermissionDenied('Недостаточно прав для загрузки файлов.')
    if category is not None:category=valid_category(instance,category)
    if not file:raise ValidationError('Выберите файл.')
    if file.size>MAX_SIZE:raise ValidationError('Размер одного файла должен быть не больше 100 МБ.')
    if not file.size:raise ValidationError('Файл пустой.')
    token_field=serializers.UUIDField();token=token_field.run_validation(token)
    name=PurePosixPath(file.name.replace('\\','/')).name
    name=''.join(c for c in name if ord(c)>=32 and ord(c)!=127)[:250] or 'Файл'
    digest=hashlib.sha256()
    for chunk in file.chunks():digest.update(chunk)
    fingerprint=digest.hexdigest();file.seek(0)
    saved=None;storage=OrderInstanceDocument._meta.get_field('file').storage
    try:
        with transaction.atomic():
            current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
            if not can_edit_order(user,current):raise PermissionDenied('Недостаточно прав для загрузки файлов.')
            active=get_object_or_404(current.instances.select_for_update(),pk=instance.pk,is_active=True)
            previous=OrderInstanceDocument.objects.filter(creation_token=token).first()
            if previous:
                if previous.task_category!=category or previous.instance_id!=active.pk or previous.created_by_id!=user.pk or previous.fingerprint!=fingerprint or previous.name!=name or not previous.is_active:raise ValidationError('Идентификатор загрузки уже использован. Выберите файл заново.')
                return previous,False
            row=OrderInstanceDocument(instance=active,task_category=category,name=name,size=file.size,created_by=user,creation_token=token,fingerprint=fingerprint)
            row.file.save(uuid.uuid4().hex, file,save=False);saved=row.file.name
            row.save()
            OrderEvent.objects.create(order=current,actor=user,action='instance_document_added',details={'instance_id':instance.pk,'document_id':row.pk})
        return row,True
    except Exception:
        if saved:storage.delete(saved)
        raise

def remove(order,document,user):
    from .views import can_edit_order
    with transaction.atomic():
        current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
        if not can_edit_order(user,current):raise PermissionDenied('Недостаточно прав для удаления файлов.')
        row=OrderInstanceDocument.objects.select_for_update().get(pk=document.pk)
        if row.is_active:
            row.is_active=False;row.save(update_fields=['is_active'])
            OrderEvent.objects.create(order=current,actor=user,action='instance_document_removed',details={'instance_id':row.instance_id,'document_id':row.pk})

def download(document,preview=False):
    mime=preview_type(document) if preview else None
    if preview and mime=='text/html':
        from .office_preview import preview as office_preview
        return office_preview(document)
    if preview and not mime:raise ValidationError('Для этого файла доступно только скачивание.')
    try:response=FileResponse(document.file.open('rb'),as_attachment=not preview,filename=document.name,content_type=mime or 'application/octet-stream')
    except FileNotFoundError:raise NotFound('Файл не найден.')
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    if preview:response['X-Frame-Options']='SAMEORIGIN'
    return response


def valid_category(instance,value):
    from .instance_executors_backend import groups
    category=serializers.IntegerField(min_value=1).run_validation(value)
    if category not in groups(instance):raise ValidationError('В изделии нет услуг этой категории.')
    return category


def attach_to_task(order,document,user,category):
    from .views import can_edit_order
    with transaction.atomic():
        current=Order.objects.select_for_update().select_related('responsible').get(pk=order.pk)
        if not can_edit_order(user,current):raise PermissionDenied('Недостаточно прав для изменения задания.')
        row=OrderInstanceDocument.objects.select_for_update().select_related('instance').get(pk=document.pk,is_active=True)
        category=valid_category(row.instance,category)
        if row.task_category is not None and row.task_category!=category:raise ValidationError('Файл уже прикреплён к другому заданию.')
        if row.task_category!=category:
            row.task_category=category;row.save(update_fields=['task_category'])
            OrderEvent.objects.create(order=current,actor=user,action='instance_document_attached',details={'instance_id':row.instance_id,'document_id':row.pk,'category_id':category})
        return row
