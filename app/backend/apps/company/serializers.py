from decimal import Decimal
from rest_framework import serializers
from .models import Company, Organization

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["name", "phone", "email", "currency", "instagram", "vk", "telegram", "website"]
        extra_kwargs = {f: {"required": True, "allow_blank": False} for f in ["name", "phone", "email", "currency"]}

class OrganizationSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()
    signature = serializers.SerializerMethodField()
    stamp = serializers.SerializerMethodField()
    def image_url(self, obj, kind):
        return f"/api/organizations/{obj.pk}/images/{kind}/" if getattr(obj, kind) else None
    def get_logo(self, obj): return self.image_url(obj, "logo")
    def get_signature(self, obj): return self.image_url(obj, "signature")
    def get_stamp(self, obj): return self.image_url(obj, "stamp")
    class Meta:
        model = Organization
        fields = ["id", "kind", "full_name", "short_name", "legal_address", "inn", "kpp", "ogrn", "ogrnip",
            "director", "accountant", "uses_vat", "vat_mode", "vat_rate", "bank_name", "bank_bik", "bank_account",
            "bank_correspondent_account", "logo", "signature", "stamp", "is_archived"]
        read_only_fields = ["id", "is_archived"]
    def validate_vat_rate(self, value):
        if not Decimal(0) <= value <= Decimal(100):
            raise serializers.ValidationError("Укажите процент от 0 до 100.")
        return value

class ImageSerializer(serializers.Serializer):
    image = serializers.ImageField()
    def validate_image(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Размер изображения не должен превышать 5 МБ.")
        if value.image.format not in ("JPEG", "PNG", "WEBP"):
            raise serializers.ValidationError("Используйте PNG, JPEG или WebP.")
        return value
