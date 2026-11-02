import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from .models import Employee
from .roles import ROLES, CONTRACTOR_ROLES

class EmployeeSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    def get_avatar(self, obj):
        return f"/api/employees/{obj.pk}/avatar/?v={obj.updated_at.timestamp()}" if obj.avatar else None
    username = serializers.CharField(max_length=25, required=False, allow_blank=True)
    pin = serializers.CharField(write_only=True, required=False)
    pin_confirmation = serializers.CharField(write_only=True, required=False)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=list(ROLES)), allow_empty=False)
    class Meta:
        model = Employee
        fields = ["id", "kind", "username", "full_name", "phone", "email", "timezone", "roles", "order_suffix",
            "own_orders_only", "own_clients_only", "all_financial_operations", "can_export_stock", "is_blocked",
            "position", "about", "telegram", "avatar", "pin", "pin_confirmation"]
        read_only_fields = ["id"]
    def to_representation(self, instance):
        result = super().to_representation(instance)
        result["username"] = instance.user.username if instance.user_id else ""
        return result
    def validate_timezone(self, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise serializers.ValidationError("Выберите действительный часовой пояс.")
        return value
    def validate(self, attrs):
        current = self.instance
        kind = attrs.get("kind", current.kind if current else "staff")
        roles = attrs.get("roles", current.roles if current else [])
        if not roles: raise serializers.ValidationError({"roles": "Назначьте хотя бы одну роль."})
        attrs["roles"] = list(dict.fromkeys(roles))
        if current and kind != current.kind:
            raise serializers.ValidationError({"kind": "Вид сотрудника изменить нельзя. Создайте новую карточку."})
        if kind == "contractor":
            if not set(roles) <= CONTRACTOR_ROLES:
                raise serializers.ValidationError({"roles": "Подрядчику доступны роли исполнителей: мастер, монтажник, водитель, декоратор."})
            if attrs.get("username") or attrs.get("pin") or attrs.get("pin_confirmation"):
                raise serializers.ValidationError({"username": "У подрядчика нет логина и ПИН-кода."})
        else:
            username = attrs.get("username", current.user.username if current and current.user_id else "")
            if not re.fullmatch(r"[A-Za-zА-Яа-яЁё0-9.@_+-]{1,25}", username):
                raise serializers.ValidationError({"username": "Логин: до 25 русских или латинских букв, цифр и символов . @ _ + -."})
            others = get_user_model().objects.all()
            if current and current.user_id: others = others.exclude(pk=current.user_id)
            if any(existing.casefold() == username.casefold() for existing in others.values_list("username", flat=True)): raise serializers.ValidationError({"username": "Такой логин уже существует."})
            attrs["username"] = username
            if not current:
                pin = attrs.get("pin", "")
                if pin != attrs.get("pin_confirmation", ""):
                    raise serializers.ValidationError({"pin_confirmation": "ПИН-коды не совпадают."})
                try: validate_password(pin)
                except DjangoValidationError as e: raise serializers.ValidationError({"pin": e.messages})
            elif "pin" in attrs or "pin_confirmation" in attrs:
                raise serializers.ValidationError({"pin": "Используйте отдельную кнопку изменения ПИН-кода."})
        if "manager" not in roles:
            attrs.update(own_orders_only=False, own_clients_only=False, all_financial_operations=False)
        if not set(roles).intersection({"manager","owner"}): attrs["order_suffix"] = ""
        if "procurement" not in roles: attrs["can_export_stock"] = False
        return attrs
    @transaction.atomic
    def create(self, validated_data):
        username = validated_data.pop("username", "")
        pin = validated_data.pop("pin", "")
        validated_data.pop("pin_confirmation", None)
        if validated_data.get("kind", "staff") == "staff":
            owner = "owner" in validated_data["roles"]
            user = get_user_model().objects.create_user(username=username, password=pin,
                is_active=not validated_data.get("is_blocked", False), is_superuser=owner, is_staff=owner)
            validated_data["user"] = user
        return super().create(validated_data)
    @transaction.atomic
    def update(self, instance, validated_data):
        username = validated_data.pop("username", None)
        validated_data.pop("pin", None); validated_data.pop("pin_confirmation", None)
        if instance.user_id:
            user = get_user_model().objects.select_for_update().get(pk=instance.user_id)
            # Serialize owner updates to prevent accidentally removing the last active owner.
            owners = list(get_user_model().objects.select_for_update().filter(is_superuser=True, is_active=True))
            blocked = validated_data.get("is_blocked", instance.is_blocked)
            owner = "owner" in validated_data.get("roles", instance.roles)
            if user.pk == self.context["request"].user.pk and blocked:
                raise serializers.ValidationError({"is_blocked": "Нельзя заблокировать свою учётную запись."})
            if user.is_superuser and user.is_active and (blocked or not owner) and not any(o.pk != user.pk for o in owners):
                raise serializers.ValidationError({"roles": "В CRM должен остаться хотя бы один активный собственник."})
            if username is not None: user.username = username
            user.is_active = not blocked; user.is_superuser = owner; user.is_staff = owner
            user.save(update_fields=["username", "is_active", "is_superuser", "is_staff"])
        return super().update(instance, validated_data)

class PinSerializer(serializers.Serializer):
    pin = serializers.CharField(write_only=True)
    pin_confirmation = serializers.CharField(write_only=True)
    def validate(self, attrs):
        if attrs["pin"] != attrs["pin_confirmation"]:
            raise serializers.ValidationError({"pin_confirmation": "ПИН-коды не совпадают."})
        try: validate_password(attrs["pin"])
        except DjangoValidationError as e: raise serializers.ValidationError({"pin": e.messages})
        return attrs

class OwnProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(max_length=40, allow_blank=False)
    class Meta:
        model = Employee
        fields = ["full_name", "phone", "email", "timezone", "position", "about", "telegram"]
    def validate_timezone(self, value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError): raise serializers.ValidationError("Выберите действительный часовой пояс.")
        return value
