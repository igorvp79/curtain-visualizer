"""Root category decides whether work belongs to the workshop."""
from .models import ServiceCategory

def production_map():
    rows={r.pk:r for r in ServiceCategory.objects.all()}
    result={}
    for key,row in rows.items():
        seen=set()
        while row.parent_id in rows and row.pk not in seen:
            seen.add(row.pk);row=rows[row.parent_id]
        result[key]=row.participates_in_production
    return result
