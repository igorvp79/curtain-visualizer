"""Visibility rule used by the Orders API, including direct IDs."""
from enum import StrEnum
from .models import Employee


class OrderVisibility(StrEnum):
    NONE = 'none'
    OWN = 'own'
    ALL = 'all'


def get_order_visibility(user):
    if not user.is_authenticated or not user.is_active:
        return OrderVisibility.NONE
    if user.is_superuser:
        return OrderVisibility.ALL
    employee = Employee.objects.filter(user=user, is_blocked=False).first()
    if not employee:
        return OrderVisibility.NONE
    # Cashiers must find every order at checkout, even when also designers.
    if 'cashier' in employee.roles:
        return OrderVisibility.ALL
    if 'manager' not in employee.roles:
        return OrderVisibility.NONE
    from apps.company.models import Company
    own_only = Company.objects.filter(pk=1).values_list('designer_own_orders_only', flat=True).first()
    return OrderVisibility.OWN if own_only else OrderVisibility.ALL
