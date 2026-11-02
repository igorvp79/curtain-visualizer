import re
from django.core.exceptions import ValidationError

class PinValidator:
    def validate(self, password, user=None):
        if not isinstance(password, str) or not re.fullmatch(r"[0-9]{4}", password):
            raise ValidationError("ПИН-код должен состоять ровно из четырёх цифр.", code="invalid_pin")
    def get_help_text(self):
        return "Введите ПИН-код из четырёх цифр."
